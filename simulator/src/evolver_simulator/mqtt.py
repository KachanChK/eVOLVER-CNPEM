"""Transporte MQTT 5 para telemetria simulada."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import paho.mqtt.client as mqtt
from evolver_contracts.models import (
    ExecutedCommandResult,
    PumpCommand,
    ReceivedCommandResult,
    RejectedCommandResult,
    TelemetryEvent,
)
from evolver_contracts.pilot import (
    ACTIVE_VIALS_REQUEST,
    ACTIVE_VIALS_RESPONSE,
    ActiveVial,
    AllocationRequest,
    AllocationResponse,
)
from pydantic import ValidationError

from .config import SimulatorSettings

LOGGER = logging.getLogger(__name__)
ClientFactory = Callable[..., mqtt.Client]


class MqttConnectionError(RuntimeError):
    """Falha ao estabelecer uma sessao MQTT autenticada."""


class MqttPublishError(RuntimeError):
    """Falha ao confirmar a publicacao no transporte MQTT."""


class MqttPublisher:
    """Publica ``TelemetryEvent`` com MQTT 5, QoS 1 e sem retencao."""

    def __init__(
        self,
        settings: SimulatorSettings,
        *,
        client_factory: ClientFactory = mqtt.Client,
    ) -> None:
        self._settings = settings
        self._connect_finished = threading.Event()
        self._connected = threading.Event()
        self._connect_error: str | None = None
        self._publish_results: dict[int, mqtt.ReasonCode] = {}
        self._publish_results_lock = threading.Lock()
        self._loop_started = False
        self._subscription_finished = threading.Event()
        self._subscription_error: str | None = None
        self._allocation_received = threading.Event()
        self._allocation_request_id: UUID | None = None
        self._allocations: list[ActiveVial] | None = None
        self._allocation_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._pump_states: dict[tuple[int, int], bool] = {}
        self._client = client_factory(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv5,
        )
        self._client.username_pw_set(settings.mqtt_username, settings.mqtt_simulator_password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_publish = self._on_publish
        self._client.on_subscribe = self._on_subscribe
        self._client.on_message = self._on_message

    def _on_subscribe(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _mid: int,
        reason_codes: list[mqtt.ReasonCode],
        _properties: mqtt.Properties | None,
    ) -> None:
        self._subscription_error = next(
            (str(code) for code in reason_codes if code.is_failure), None
        )
        self._subscription_finished.set()

    def _on_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        command_topic = f"evolver/v1/{self._settings.equipment_id}/commands"
        if message.topic == command_topic and not message.retain:
            threading.Thread(
                target=self._handle_command, args=(message.payload,), daemon=True,
            ).start()
            return
        if message.topic != ACTIVE_VIALS_RESPONSE or message.retain:
            return
        try:
            response = AllocationResponse.model_validate_json(message.payload)
        except ValidationError:
            return
        if response.request_id == self._allocation_request_id:
            self._allocations = response.vials
            self._allocation_received.set()

    def _handle_command(self, payload: bytes) -> None:
        with self._command_lock:
            try:
                command = PumpCommand.model_validate_json(payload)
            except ValidationError:
                LOGGER.warning("Comando de bomba inválido")
                return
            if command.equipment_id != self._settings.equipment_id:
                return
            try:
                with closing(self._state_database()) as database:
                    previous = database.execute(
                        "SELECT status, reason FROM completed_commands WHERE command_id = ?",
                        (str(command.command_id),),
                    ).fetchone()
                    if previous:
                        self._send_command_result(command, *previous)
                        return
                    reason = None
                    if command.is_expired_at(datetime.now(UTC)):
                        reason = "expired"
                    elif command.pump_id != 1 or command.experiment_run_id is None:
                        reason = "invalid_payload"
                    else:
                        try:
                            allocations = self.active_vials()
                        except (MqttConnectionError, MqttPublishError):
                            LOGGER.warning("Não foi possível verificar o experimento do comando")
                            return
                        active = next(
                            (v for v in allocations
                             if str(v.experiment_id) == command.experiment_run_id), None,
                        )
                        if active is None:
                            reason = "invalid_payload"
                    if reason:
                        with database:
                            database.execute(
                                "INSERT INTO completed_commands VALUES (?, ?, ?)",
                                (str(command.command_id), "rejected", reason),
                            )
                        self._send_command_result(command, "rejected", reason)
                        return
                    self._send_command_result(command, "received")
                    experiment_id = int(command.experiment_run_id)
                    state = command.action == "turn_on"
                    with database:
                        database.execute(
                            "INSERT OR REPLACE INTO pump_states VALUES (?, ?, ?)",
                            (experiment_id, active.vial_id, state),
                        )
                        database.execute(
                            "INSERT INTO completed_commands VALUES (?, ?, ?)",
                            (str(command.command_id), "executed", None),
                        )
                    self._pump_states[experiment_id, active.vial_id] = state
                    self._send_command_result(command, "executed")
            except (OSError, sqlite3.Error) as exc:
                LOGGER.error("Estado da bomba não persistido: %s", exc)

    def _state_database(self) -> sqlite3.Connection:
        path = self._settings.pump_state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        database = sqlite3.connect(path)
        try:
            database.execute("""
                CREATE TABLE IF NOT EXISTS pump_states (
                    experiment_id INTEGER NOT NULL, vial_id INTEGER NOT NULL,
                    is_on INTEGER NOT NULL,
                    PRIMARY KEY (experiment_id, vial_id)
                )
            """)
            database.execute("""
                CREATE TABLE IF NOT EXISTS completed_commands (
                    command_id TEXT PRIMARY KEY, status TEXT NOT NULL, reason TEXT
                )
            """)
            self._pump_states = {
                (experiment_id, vial_id): bool(is_on)
                for experiment_id, vial_id, is_on in database.execute(
                    "SELECT experiment_id, vial_id, is_on FROM pump_states"
                )
            }
        except Exception:
            database.close()
            raise
        return database

    def _send_command_result(
        self, command: PumpCommand, status: str, reason: str | None = None,
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
        self._publish_payload(
            f"evolver/v1/{self._settings.equipment_id}/command-results",
            result.model_dump_json(),
        )

    def _on_connect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            self._connect_error = str(reason_code)
        else:
            result, _mid = self._client.subscribe(
                f"evolver/v1/{self._settings.equipment_id}/commands", qos=1,
            )
            if result == mqtt.MQTT_ERR_SUCCESS:
                self._connected.set()
            else:
                self._connect_error = f"MQTT command subscription failed: {result}"
        self._connect_finished.set()

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        _reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        self._connected.clear()

    def _on_publish(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        mid: int,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        with self._publish_results_lock:
            self._publish_results[mid] = reason_code

    def connect(self) -> None:
        self._connect_finished.clear()
        self._connected.clear()
        self._connect_error = None
        try:
            result = self._client.connect(
                self._settings.mqtt_host,
                self._settings.mqtt_port,
                self._settings.mqtt_keepalive_seconds,
                clean_start=mqtt.MQTT_CLEAN_START_FIRST_ONLY,
            )
        except (OSError, mqtt.WebsocketConnectionError) as exc:
            raise MqttConnectionError(f"could not connect to MQTT broker: {exc}") from exc
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise MqttConnectionError(f"MQTT connect returned error code {result}")

        self._client.loop_start()
        self._loop_started = True
        if not self._connect_finished.wait(self._settings.mqtt_connect_timeout_seconds):
            self.close()
            raise MqttConnectionError("timed out waiting for MQTT CONNACK")
        if self._connect_error is not None:
            error = self._connect_error
            self.close()
            raise MqttConnectionError(f"MQTT connection refused: {error}")

        LOGGER.info(
            "Conectado ao broker MQTT em %s:%s como %s",
            self._settings.mqtt_host,
            self._settings.mqtt_port,
            self._settings.mqtt_username,
        )

    def publish(self, event: TelemetryEvent) -> None:
        if not self._connected.is_set():
            raise MqttPublishError("MQTT client is not connected")

        self._publish_payload(self._settings.telemetry_topic, event.model_dump_json())
        labels = {"od": "OD", "ph": "pH", "temperature": "Temperatura"}
        unit = " °C" if event.measurement_type == "temperature" else ""
        LOGGER.info(
            "Frasco %s | %s: %s%s | Enviado ao MQTT | event_id=%s sequence=%s",
            event.vial_id,
            labels[event.measurement_type],
            event.value,
            unit,
            event.event_id,
            event.sequence,
        )

    def active_vials(self) -> list[ActiveVial]:
        with self._allocation_lock:
            return self._active_vials_locked()

    def _active_vials_locked(self) -> list[ActiveVial]:
        if not self._connected.is_set():
            raise MqttConnectionError("MQTT client is not connected")
        self._subscription_finished.clear()
        self._subscription_error = None
        result, _mid = self._client.subscribe(ACTIVE_VIALS_RESPONSE, qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise MqttConnectionError(f"MQTT subscribe returned error code {result}")
        if not self._subscription_finished.wait(self._settings.mqtt_connect_timeout_seconds):
            raise MqttConnectionError("timed out waiting for active vial subscription")
        if self._subscription_error is not None:
            raise MqttConnectionError(
                f"active vial subscription rejected: {self._subscription_error}"
            )
        self._allocation_request_id = uuid4()
        self._allocation_received.clear()
        self._allocations = None
        request = AllocationRequest(request_id=self._allocation_request_id)
        self._publish_payload(ACTIVE_VIALS_REQUEST, request.model_dump_json())
        if not self._allocation_received.wait(self._settings.mqtt_connect_timeout_seconds):
            raise MqttConnectionError("timed out waiting for active vials from ingestion")
        assert self._allocations is not None
        return self._allocations

    def _publish_payload(self, topic: str, payload: str) -> None:
        info = self._client.publish(
            topic,
            payload=payload,
            qos=1,
            retain=False,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise MqttPublishError(f"MQTT publish returned error code {info.rc}")
        try:
            info.wait_for_publish(timeout=self._settings.mqtt_publish_timeout_seconds)
        except RuntimeError as exc:
            raise MqttPublishError(f"MQTT publication failed: {exc}") from exc
        if not info.is_published():
            raise MqttPublishError("timed out waiting for MQTT PUBACK")

        with self._publish_results_lock:
            reason_code = self._publish_results.pop(info.mid, None)
        if reason_code is None:
            raise MqttPublishError(f"MQTT PUBACK result missing for message {info.mid}")
        if reason_code.is_failure:
            raise MqttPublishError(f"MQTT PUBACK rejected message {info.mid}: {reason_code}")

    def close(self) -> None:
        self._connected.clear()
        if not self._loop_started:
            return
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()
            self._loop_started = False
            with self._publish_results_lock:
                self._publish_results.clear()
