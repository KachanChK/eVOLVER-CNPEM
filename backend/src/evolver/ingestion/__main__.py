"""Store versioned simulator telemetry and answer active vial queries."""

from __future__ import annotations

import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from socket import IPPROTO_TCP, TCP_NODELAY

from evolver_contracts.models import CommandResultPayload
from evolver_contracts.pilot import (
    ACTIVE_VIALS_REQUEST,
    ACTIVE_VIALS_RESPONSE,
    EQUIPMENT_ID,
    AllocationRequest,
    AllocationResponse,
)
from paho.mqtt import client as mqtt
from pydantic import TypeAdapter
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .control import (
    command_is_current,
    expire_commands,
    invalidate_controls,
    pending_commands,
    queue_safety_offs,
    record_result,
)
from .telemetry import store_v1_message as store_v1_message
from .telemetry import telemetry_is_live, telemetry_outcome


def active_vials(engine: Engine, payload: bytes) -> AllocationResponse:
    request = AllocationRequest.model_validate_json(payload)
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text("""
                SELECT e.vial_id, e.id AS experiment_id, e.allocation_id
                FROM experiments e JOIN vials v ON v.vial_id = e.vial_id
                WHERE v.equipment_id = :equipment_id AND e.ended_at IS NULL
                ORDER BY e.vial_id
            """),
                {"equipment_id": EQUIPMENT_ID},
            )
            .mappings()
            .all()
        )
    return AllocationResponse.model_validate({"request_id": request.request_id, "vials": rows})


def main() -> None:
    engine = create_engine(
        os.environ["DATABASE_URL"], pool_pre_ping=True,
        connect_args={"connect_timeout": 2, "options": "-c statement_timeout=3000"},
    )
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5, reconnect_on_failure=False,
    )
    client.connect_timeout = 2
    client.on_socket_open = lambda _client, _userdata, socket: socket.setsockopt(
        IPPROTO_TCP, TCP_NODELAY, 1,
    )
    client.username_pw_set("evolver-ingestion", os.environ["MQTT_INGESTION_PASSWORD"])
    host = os.getenv("MQTT_HOST", "127.0.0.1")
    port = int(os.getenv("MQTT_PORT", "1883"))
    command_results_topic = f"evolver/v1/{EQUIPMENT_ID}/command-results"
    next_connect = next_database_poll = 0.0
    invalidate_pending = safety_offs_pending = True
    database_degraded = False
    awaiting_puback = {}
    history = ThreadPoolExecutor(max_workers=6)
    pending_history: set[Future[tuple[str, str] | None]] = set()

    def database_failed(exc: SQLAlchemyError) -> None:
        nonlocal next_database_poll, invalidate_pending, safety_offs_pending, database_degraded
        if not database_degraded:
            print(f"Banco indisponível para ingestão; nova tentativa em 1 s: {exc}", flush=True)
        database_degraded = True
        next_database_poll = time.monotonic() + 1
        invalidate_pending = safety_offs_pending = True
        for future in pending_history:
            future.cancel()

    def publish_outcome(outcome: tuple[str, str] | None) -> None:
        if outcome is not None and client.is_connected():
            client.publish(*outcome, qos=1, retain=False)

    def on_connect(client, userdata, flags, reason_code, properties) -> None:
        nonlocal invalidate_pending, safety_offs_pending
        if reason_code.is_failure:
            print(f"Conexão MQTT recusada: {reason_code}", flush=True)
            return
        invalidate_pending = safety_offs_pending = True
        client.subscribe([
            ("evolver/v1/+/telemetry", 1),
            (ACTIVE_VIALS_REQUEST, 1),
            (command_results_topic, 1),
        ])
        print("Ingestão conectada ao MQTT.", flush=True)

    def on_disconnect(client, userdata, flags, reason_code, properties) -> None:
        nonlocal invalidate_pending, safety_offs_pending
        invalidate_pending = safety_offs_pending = True

    def on_message(client, userdata, message) -> None:
        if message.retain or (invalidate_pending and time.monotonic() < next_database_poll):
            return
        try:
            if message.topic == ACTIVE_VIALS_REQUEST:
                response = active_vials(engine, message.payload)
                client.publish(ACTIVE_VIALS_RESPONSE, response.model_dump_json(), qos=1)
            elif message.topic == command_results_topic:
                result = TypeAdapter(CommandResultPayload).validate_json(message.payload)
                if result.equipment_id != EQUIPMENT_ID:
                    raise ValueError("equipamento não corresponde ao resultado")
                with engine.begin() as connection:
                    record_result(connection, result)
            elif telemetry_is_live(message.properties):
                publish_outcome(telemetry_outcome(
                    engine, message, control_ready=not (invalidate_pending or safety_offs_pending),
                ))
            elif len(pending_history) < 128:
                pending_history.add(
                    history.submit(telemetry_outcome, engine, message, control_ready=False),
                )
        except SQLAlchemyError as exc:
            database_failed(exc)
        except (ValueError, OSError, RuntimeError) as exc:
            print(f"Mensagem sem desfecho: {exc}", flush=True)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    try:
        network_open = False
        while True:
            monotonic_now = time.monotonic()
            if not network_open and monotonic_now >= next_connect:
                try:
                    network_open = client.connect(host, port) == mqtt.MQTT_ERR_SUCCESS
                except OSError as exc:
                    print(f"Broker MQTT indisponível; nova tentativa em 1 s: {exc}", flush=True)
                next_connect = time.monotonic() + 1
            if network_open:
                timeout = 0.01 if pending_history else 0.05
                network_open = client.loop(timeout=timeout) == mqtt.MQTT_ERR_SUCCESS
            else:
                time.sleep(0.05)

            for future in tuple(pending_history):
                if not future.done():
                    continue
                pending_history.remove(future)
                if future.cancelled():
                    continue
                try:
                    publish_outcome(future.result())
                except SQLAlchemyError as exc:
                    if isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None) in (
                        "40001", "40P01", "55P03", "57014",
                    ):
                        print(f"Telemetria histórica sem desfecho: {exc.orig}", flush=True)
                    else:
                        database_failed(exc)
                except (ValueError, OSError, RuntimeError) as exc:
                    print(f"Mensagem sem desfecho: {exc}", flush=True)

            if time.monotonic() < next_database_poll:
                continue
            next_database_poll = time.monotonic() + 0.2
            now = datetime.now(UTC)
            connected = client.is_connected()
            try:
                with engine.begin() as connection:
                    if invalidate_pending:
                        invalidate_controls(connection)
                    expire_commands(connection, now)
                    if connected and safety_offs_pending:
                        queue_safety_offs(connection, now)
                    commands = pending_commands(connection, now) if connected else []
                if database_degraded:
                    print("Conexão da ingestão com o banco recuperada.", flush=True)
                    database_degraded = False
                invalidate_pending = False
                if connected:
                    safety_offs_pending = False
                for command in commands:
                    with engine.begin() as connection:
                        if not command_is_current(connection, command):
                            continue
                        claimed = connection.execute(text("""
                            UPDATE pump_commands SET sent_at = clock_timestamp()
                            WHERE command_id = :id AND sent_at IS NULL
                        """), {"id": command.command_id}).rowcount
                    if not claimed:
                        continue
                    # Recheck after committing the claim, under the same lock as the pause.
                    with engine.begin() as connection:
                        if not command_is_current(connection, command, claimed_here=True):
                            continue
                        info = client.publish(
                            f"evolver/v1/{EQUIPMENT_ID}/commands",
                            command.model_dump_json(), qos=1, retain=False,
                        )
                    if info.rc == mqtt.MQTT_ERR_SUCCESS:
                        awaiting_puback[command.command_id] = (info, command.expires_at)
                for command_id, (info, expires_at) in list(awaiting_puback.items()):
                    if info.is_published():
                        with engine.begin() as connection:
                            connection.execute(text("""
                                UPDATE pump_commands SET puback_at = clock_timestamp()
                                WHERE command_id = :command_id
                            """), {"command_id": command_id})
                    elif expires_at > now:
                        continue
                    del awaiting_puback[command_id]
            except SQLAlchemyError as exc:
                database_failed(exc)
            except (RuntimeError, OSError) as exc:
                print(f"Comando sem confirmação de transporte: {exc}", flush=True)
    finally:
        client.disconnect()
        history.shutdown(wait=True, cancel_futures=True)
        engine.dispose()


if __name__ == "__main__":
    main()
