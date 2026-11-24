"""Transporte MQTT 5 para telemetria simulada."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from queue import Empty, SimpleQueue
from socket import IPPROTO_TCP, TCP_NODELAY
from typing import Any
from uuid import UUID, uuid4

import paho.mqtt.client as mqtt
from evolver_contracts.models import (
    ExecutedCommandResult,
    PumpCommand,
    ReceivedCommandResult,
    RejectedCommandResult,
    TelemetryAcknowledgement,
    TelemetryRejection,
)
from evolver_contracts.pilot import (
    ACTIVE_VIALS_REQUEST,
    ACTIVE_VIALS_RESPONSE,
    TELEMETRY_MODE_PROPERTY,
    ActiveVial,
    AllocationRequest,
    AllocationResponse,
)
from pydantic import ValidationError

from .config import SimulatorSettings

LOGGER = logging.getLogger(__name__)
PUMP_GROUP_MEMBERS = (1, 2, 3)
ClientFactory = Callable[..., mqtt.Client]


class MqttConnectionError(RuntimeError):
    """Falha ao estabelecer uma sessao MQTT autenticada."""


class MqttPublishError(RuntimeError):
    """Falha ao confirmar a publicacao no transporte MQTT."""


class PumpStateError(MqttConnectionError):
    """O estado durável das bombas não pôde ser carregado."""


@dataclass
class AllocationQuery:
    request_id: UUID
    session: int
    finished: threading.Event = field(default_factory=threading.Event)
    response: AllocationResponse | None = None


class MqttPublisher:
    """Recria a sessão MQTT e entrega respostas ao ciclo da fila."""

    def __init__(
        self,
        settings: SimulatorSettings,
        *,
        client_factory: ClientFactory = mqtt.Client,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._client: mqtt.Client | None = None
        self._session = 0
        self._connect_finished = threading.Event()
        self._connected = threading.Event()
        self._connect_error: str | None = None
        self._publish_results: OrderedDict[int, mqtt.ReasonCode] = OrderedDict()
        self._publish_results_lock = threading.Lock()
        self._allocation_lock = threading.Lock()
        self._queries: dict[UUID, AllocationQuery] = {}
        self._outcomes: SimpleQueue[TelemetryAcknowledgement | TelemetryRejection] = SimpleQueue()
        self._command_executor = ThreadPoolExecutor(max_workers=1)
        self._command_lock = threading.Lock()
        self._pump_state_lock = threading.Lock()
        self._pump_states: dict[tuple[str, int], bool] = {}
        prefix = self._settings.telemetry_topic
        self._ack_topic = f"{prefix}/ack"
        self._rejection_topic = f"{prefix}/rejection"
        self._command_topic = f"evolver/v1/{settings.equipment_id}/commands"

    @property
    def session(self) -> int | None:
        return self._session if self._connected.is_set() else None

    def _on_subscribe(
        self, client, _userdata, _mid, reason_codes, _properties,
    ) -> None:
        if client is not self._client:
            return
        if len(reason_codes) != 4 or any(code.is_failure for code in reason_codes):
            self._connect_error = f"MQTT subscription refused: {reason_codes}"
        else:
            self._connected.set()
        self._connect_finished.set()

    def _on_message(self, client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        if client is not self._client or message.retain:
            return
        session = self.session
        if session is None:
            return
        if message.topic == self._command_topic:
            self._command_executor.submit(self._handle_command, message.payload, session)
            return
        try:
            if message.topic == ACTIVE_VIALS_RESPONSE:
                response = AllocationResponse.model_validate_json(message.payload)
                with self._allocation_lock:
                    query = self._queries.pop(response.request_id, None)
                    if query is not None and query.session == session:
                        query.response = response
                        query.finished.set()
                return
            if message.topic == self._ack_topic:
                outcome = TelemetryAcknowledgement.model_validate_json(message.payload)
            elif message.topic == self._rejection_topic:
                outcome = TelemetryRejection.model_validate_json(message.payload)
            else:
                return
            if outcome.equipment_id == self._settings.equipment_id:
                self._outcomes.put(outcome)
        except ValidationError:
            LOGGER.warning("Resposta MQTT inválida em %s", message.topic)

    def outcomes(self):
        while True:
            try:
                yield self._outcomes.get_nowait()
            except Empty:
                return

    def _handle_command(self, payload: bytes, session: int | None = None) -> None:
        session = self.session if session is None else session
        with self._command_lock:
            try:
                self._apply_command(payload, session)
            except (MqttConnectionError, MqttPublishError) as exc:
                LOGGER.warning("Resultado do comando sem confirmação MQTT: %s", exc)

    def _apply_command(self, payload: bytes, session: int | None) -> None:
        if session is None or session != self.session:
            return
        try:
            command = PumpCommand.model_validate_json(payload)
        except ValidationError:
            LOGGER.warning("Comando do grupo de bombas inválido")
            return
        if command.equipment_id != self._settings.equipment_id:
            return
        try:
            allocation_id = str(UUID(command.experiment_run_id or ""))
        except ValueError:
            self._send_command_result(command, "rejected", "invalid_payload", session=session)
            return
        try:
            allocations = self.active_vials(session=session)
        except (MqttConnectionError, MqttPublishError):
            LOGGER.warning("Não foi possível verificar o experimento do comando")
            return
        if session != self.session:
            return
        active = next((v for v in allocations if str(v.allocation_id) == allocation_id), None)
        if active is None:
            self._send_command_result(command, "rejected", "invalid_payload", session=session)
            return
        try:
            with closing(self._state_database()) as database:
                previous = database.execute(
                    """SELECT status, reason FROM completed_allocation_commands
                    WHERE allocation_id = ? AND command_id = ?""",
                    (allocation_id, str(command.command_id)),
                ).fetchone()
                if previous:
                    self._send_command_result(command, *previous, session=session)
                    return
                with database:
                    reason = "expired" if command.is_expired_at(datetime.now(UTC)) else None
                    if reason is None:
                        issued_at = command.created_at.astimezone(UTC).isoformat(
                            timespec="microseconds",
                        )
                        advanced = database.execute("""
                            INSERT INTO allocation_pump_order VALUES (?, ?)
                            ON CONFLICT (allocation_id) DO UPDATE
                            SET issued_at = excluded.issued_at
                            WHERE excluded.issued_at > allocation_pump_order.issued_at
                        """, (allocation_id, issued_at)).rowcount
                        if not advanced:
                            reason = "invalid_payload"
                        else:
                            state = command.action == "turn_on"
                            database.execute(
                                "INSERT OR REPLACE INTO allocation_pump_states "
                                "VALUES (?, ?, ?)",
                                (allocation_id, active.vial_id, state),
                            )
                    database.execute(
                        "INSERT INTO completed_allocation_commands VALUES (?, ?, ?, ?)",
                        (allocation_id, str(command.command_id),
                         "rejected" if reason else "executed", reason),
                    )
                if reason:
                    self._send_command_result(command, "rejected", reason, session=session)
                    return
                with self._pump_state_lock:
                    self._pump_states[allocation_id, active.vial_id] = state
                LOGGER.info(
                    "Ação %s aplicada ao grupo de bombas %s (command_id=%s)",
                    command.action, list(PUMP_GROUP_MEMBERS), command.command_id,
                )
                self._send_command_result(command, "received", session=session)
                self._send_command_result(command, "executed", session=session)
        except (OSError, sqlite3.Error) as exc:
            LOGGER.error("Estado do grupo de bombas não persistido: %s", exc)

    def _state_database(self) -> sqlite3.Connection:
        path = self._settings.pump_state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        database = sqlite3.connect(path)
        try:
            database.execute("""
                CREATE TABLE IF NOT EXISTS allocation_pump_states (
                    allocation_id TEXT NOT NULL, vial_id INTEGER NOT NULL,
                    is_on INTEGER NOT NULL,
                    PRIMARY KEY (allocation_id, vial_id)
                )
            """)
            database.execute("""
                CREATE TABLE IF NOT EXISTS completed_allocation_commands (
                    allocation_id TEXT NOT NULL, command_id TEXT NOT NULL,
                    status TEXT NOT NULL, reason TEXT,
                    PRIMARY KEY (allocation_id, command_id)
                )
            """)
            database.execute("""
                CREATE TABLE IF NOT EXISTS allocation_pump_order (
                    allocation_id TEXT PRIMARY KEY, issued_at TEXT NOT NULL
                )
            """)
        except Exception:
            database.close()
            raise
        return database

    def _send_command_result(
        self, command: PumpCommand, status: str, reason: str | None = None, *, session: int,
    ) -> None:
        fields = dict(
            schema_version="1.0", command_id=command.command_id,
            equipment_id=command.equipment_id, simulated=True,
            reported_at=datetime.now(UTC),
        )
        if status == "received":
            result = ReceivedCommandResult(status="received", **fields)
        elif status == "executed":
            result = ExecutedCommandResult(status="executed", **fields)
        else:
            result = RejectedCommandResult(status="rejected", reason_code=reason, **fields)
        info = self._publish(
            f"evolver/v1/{self._settings.equipment_id}/command-results",
            result.model_dump_json(), session=session,
        )
        self._wait_for_puback(info, session)

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            self._connect_error = str(reason_code)
        else:
            options = mqtt.SubscribeOptions(qos=1, retainAsPublished=True)
            result, _mid = client.subscribe([
                (self._command_topic, options),
                (ACTIVE_VIALS_RESPONSE, options),
                (self._ack_topic, options),
                (self._rejection_topic, options),
            ])
            if result == mqtt.MQTT_ERR_SUCCESS:
                return
            self._connect_error = f"MQTT subscribe failed: {result}"
        self._connect_finished.set()

    def _on_disconnect(self, client, _userdata, _flags, _reason_code, _properties) -> None:
        if client is self._client:
            self._connected.clear()
            self._connect_finished.set()
            with self._allocation_lock:
                for query in self._queries.values():
                    query.finished.set()
                self._queries.clear()

    def _on_publish(self, client, _userdata, mid, reason_code, _properties) -> None:
        if client is self._client:
            with self._publish_results_lock:
                self._publish_results[mid] = reason_code
                if len(self._publish_results) > 1024:
                    self._publish_results.popitem(last=False)

    def connect(self) -> None:
        self.disconnect()
        self._connect_finished.clear()
        self._connect_error = None
        try:
            with (
                self._command_lock,
                self._pump_state_lock,
                closing(self._state_database()) as database,
            ):
                self._pump_states = {
                    (allocation_id, vial_id): bool(is_on)
                    for allocation_id, vial_id, is_on in database.execute(
                        "SELECT allocation_id, vial_id, is_on FROM allocation_pump_states"
                    )
                }
        except (OSError, sqlite3.Error) as exc:
            raise PumpStateError("não foi possível carregar o estado do grupo de bombas") from exc
        client = self._client_factory(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._settings.mqtt_client_id, protocol=mqtt.MQTTv5,
            reconnect_on_failure=False,
        )
        client.connect_timeout = self._settings.mqtt_connect_timeout_seconds
        # Leave transport space for discovery and command results alongside the application window.
        client.max_inflight_messages_set(256)
        client.max_queued_messages_set(256)
        client.username_pw_set(self._settings.mqtt_username, self._settings.mqtt_simulator_password)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_publish = self._on_publish
        client.on_subscribe = self._on_subscribe
        client.on_message = self._on_message
        client.on_socket_open = lambda _client, _userdata, socket: socket.setsockopt(
            IPPROTO_TCP, TCP_NODELAY, 1,
        )
        self._session += 1
        self._client = client
        try:
            result = client.connect(
                self._settings.mqtt_host, self._settings.mqtt_port,
                self._settings.mqtt_keepalive_seconds, clean_start=True,
            )
            if result != mqtt.MQTT_ERR_SUCCESS:
                raise MqttConnectionError(f"MQTT connect returned error code {result}")
            client.loop_start()
            if not self._connect_finished.wait(self._settings.mqtt_connect_timeout_seconds):
                raise MqttConnectionError("timed out waiting for MQTT CONNACK/SUBACK")
            if self.session is None:
                raise MqttConnectionError(self._connect_error or "sessão MQTT encerrada")
        except (OSError, mqtt.WebsocketConnectionError, MqttConnectionError) as exc:
            self.disconnect()
            raise MqttConnectionError(f"não foi possível conectar ao MQTT: {exc}") from exc
        LOGGER.info("Sessão MQTT pronta após SUBACK")

    def pump_is_on(self, allocation: ActiveVial) -> bool:
        with self._pump_state_lock:
            return self._pump_states.get((str(allocation.allocation_id), allocation.vial_id), False)

    def request_allocations(self, session: int) -> AllocationQuery:
        query = AllocationQuery(uuid4(), session)
        request = AllocationRequest(request_id=query.request_id)
        with self._allocation_lock:
            self._queries[query.request_id] = query
        try:
            self._publish(ACTIVE_VIALS_REQUEST, request.model_dump_json(), session=session)
        except (MqttConnectionError, MqttPublishError):
            self.cancel_query(query)
            raise
        return query

    def cancel_query(self, query: AllocationQuery) -> None:
        with self._allocation_lock:
            self._queries.pop(query.request_id, None)

    def active_vials(self, *, session: int | None = None) -> list[ActiveVial]:
        session = self.session if session is None else session
        if session is None:
            raise MqttConnectionError("MQTT client is not connected")
        query = self.request_allocations(session)
        try:
            query.finished.wait(self._settings.mqtt_connect_timeout_seconds)
            if query.response is None or session != self.session:
                raise MqttConnectionError("timed out waiting for active vials from ingestion")
            return query.response.vials
        finally:
            self.cancel_query(query)

    def publish(self, payload: str | bytes, *, session: int, live: bool) -> mqtt.MQTTMessageInfo:
        properties = mqtt.Properties(mqtt.PacketTypes.PUBLISH)
        properties.UserProperty = (TELEMETRY_MODE_PROPERTY, "live" if live else "history")
        if live:
            properties.MessageExpiryInterval = 2
        return self._publish(
            self._settings.telemetry_topic, payload, session=session, properties=properties,
        )

    def _publish(
        self, topic: str, payload: str | bytes, *, session: int,
        properties: mqtt.Properties | None = None,
    ) -> mqtt.MQTTMessageInfo:
        client = self._client
        if client is None or session != self.session:
            raise MqttConnectionError("MQTT client is not connected")
        kwargs = {"properties": properties} if properties is not None else {}
        info = client.publish(topic, payload=payload, qos=1, retain=False, **kwargs)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise MqttPublishError(f"MQTT publish returned error code {info.rc}")
        return info

    def publish_outcome(self, info: mqtt.MQTTMessageInfo, session: int) -> mqtt.ReasonCode | None:
        if session != self.session or not info.is_published():
            return None
        with self._publish_results_lock:
            return self._publish_results.pop(info.mid, None)

    def _wait_for_puback(self, info: mqtt.MQTTMessageInfo, session: int) -> None:
        try:
            info.wait_for_publish(timeout=self._settings.mqtt_publish_timeout_seconds)
        except RuntimeError as exc:
            raise MqttPublishError(f"MQTT publication failed: {exc}") from exc
        reason = self.publish_outcome(info, session)
        if reason is None:
            raise MqttPublishError(f"MQTT PUBACK missing for message {info.mid}")
        if reason.is_failure:
            raise MqttPublishError(f"MQTT PUBACK rejected message {info.mid}: {reason}")

    def disconnect(self) -> None:
        client = self._client
        if client is None:
            return
        self._on_disconnect(client, None, None, None, None)
        self._client = None
        try:
            client.disconnect()
        finally:
            client.loop_stop()
            with self._publish_results_lock:
                self._publish_results.clear()

    def close(self) -> None:
        self.disconnect()
        self._command_executor.shutdown(wait=True, cancel_futures=True)
