"""Store versioned simulator telemetry and answer active vial queries."""

from __future__ import annotations

import json
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

from .alerts import alert_ranges, check_missing_data
from .control import (
    command_is_current,
    expire_commands,
    invalidate_controls,
    pending_commands,
    queue_alert_recoveries,
    queue_safety_offs,
    record_result,
)
from .telemetry import store_v1_message as store_v1_message
from .telemetry import telemetry_is_live, telemetry_outcome


def active_vials(engine: Engine, payload: bytes) -> AllocationResponse:
    request = AllocationRequest.model_validate_json(payload)
    with engine.connect() as connection:
        if request.include_test_state:
            rows = connection.execute(text("""
                SELECT e.vial_id, e.id AS experiment_id, e.allocation_id,
                       e.name AS experiment_name, e.od_min, e.od_max, c.confirmed_state,
                       NOT (c.paused OR c.ending OR c.resume_pending OR c.reconcile_required)
                           AS automatic,
                       c.pending_command_id IS NOT NULL AS pending
                FROM experiments e JOIN vials v USING (vial_id)
                LEFT JOIN pump_control c ON c.experiment_id = e.id
                WHERE v.equipment_id = :equipment_id AND e.ended_at IS NULL
                ORDER BY e.vial_id
            """), {"equipment_id": EQUIPMENT_ID}).mappings().all()
            return AllocationResponse.model_validate({
                "request_id": request.request_id, "od_alert_range": alert_ranges()["od"],
                "vials": [{
                    "vial_id": row.vial_id, "experiment_id": row.experiment_id,
                    "allocation_id": row.allocation_id, "experiment_name": row.experiment_name,
                    "pump_test": row if row.confirmed_state is not None else None,
                } for row in rows],
            })
        rows = connection.execute(text("""
            SELECT e.vial_id, e.id AS experiment_id, e.allocation_id
            FROM experiments e JOIN vials v USING (vial_id)
            WHERE v.equipment_id = :equipment_id AND e.ended_at IS NULL
            ORDER BY e.vial_id
        """), {"equipment_id": EQUIPMENT_ID}).mappings().all()
    return AllocationResponse.model_validate({"request_id": request.request_id, "vials": rows})


def main() -> None:
    alert_ranges()
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
    next_connect = next_database_poll = next_alert_check = 0.0
    invalidate_pending = safety_offs_pending = True
    database_degraded = False
    awaiting_puback = {}
    confirmed_publications = {}
    connector = ThreadPoolExecutor(max_workers=1)
    connection_attempt = None
    # Keep telemetry ordered per vial without delaying MQTT callbacks for each commit.
    live_writers = [ThreadPoolExecutor(max_workers=1) for _ in range(4)]
    pending_live: set[Future[tuple[str, str] | None]] = set()
    history = ThreadPoolExecutor(max_workers=6)
    pending_history: set[Future[tuple[str, str] | None]] = set()

    def database_failed(exc: SQLAlchemyError) -> None:
        nonlocal next_database_poll, invalidate_pending, safety_offs_pending, database_degraded
        if not database_degraded:
            print(f"Banco indisponível para ingestão; nova tentativa em 1 s: {exc}", flush=True)
        database_degraded = True
        next_database_poll = time.monotonic() + 1
        invalidate_pending = safety_offs_pending = True
        for future in pending_live | pending_history:
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

    def on_publish(client, userdata, mid, reason_code, properties) -> None:
        pending = awaiting_puback.pop(mid, None)
        if pending is not None and not reason_code.is_failure:
            confirmed_publications[pending[0]] = datetime.now(UTC)

    def store_live(message, control_ready: bool):
        return telemetry_outcome(
            engine, message, control_ready=control_ready and not invalidate_pending,
        )

    def on_message(client, userdata, message) -> None:
        if message.retain or (invalidate_pending and time.monotonic() < next_database_poll):
            return
        try:
            if message.topic == ACTIVE_VIALS_REQUEST:
                response = active_vials(engine, message.payload)
                client.publish(
                    ACTIVE_VIALS_RESPONSE, response.model_dump_json(exclude_unset=True), qos=1,
                )
            elif message.topic == command_results_topic:
                result = TypeAdapter(CommandResultPayload).validate_json(message.payload)
                if result.equipment_id != EQUIPMENT_ID:
                    raise ValueError("equipamento não corresponde ao resultado")
                with engine.begin() as connection:
                    record_result(connection, result)
            elif telemetry_is_live(message.properties):
                if len(pending_live) < 128:
                    try:
                        vial = int(json.loads(message.payload)["vial_id"])
                    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
                        vial = 0
                    writer = live_writers[vial % len(live_writers)]
                    pending_live.add(writer.submit(
                        store_live, message, not (invalidate_pending or safety_offs_pending),
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
    client.on_publish = on_publish
    try:
        network_open = False
        while True:
            monotonic_now = time.monotonic()
            if connection_attempt is not None and connection_attempt.done():
                try:
                    network_open = connection_attempt.result() == mqtt.MQTT_ERR_SUCCESS
                except OSError as exc:
                    print(f"Broker MQTT indisponível; nova tentativa em 1 s: {exc}", flush=True)
                connection_attempt = None
                next_connect = time.monotonic() + 1
            if not network_open and connection_attempt is None and monotonic_now >= next_connect:
                connection_attempt = connector.submit(client.connect, host, port)
            if network_open:
                timeout = 0.01 if pending_live or pending_history else 0.05
                network_open = client.loop(timeout=timeout) == mqtt.MQTT_ERR_SUCCESS
            else:
                time.sleep(0.05)

            for pending in (pending_live, pending_history):
                for future in tuple(pending):
                    if not future.done():
                        continue
                    pending.remove(future)
                    if future.cancelled():
                        continue
                    try:
                        publish_outcome(future.result())
                    except SQLAlchemyError as exc:
                        if isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None) in (
                            "40001", "40P01", "55P03", "57014",
                        ):
                            print(f"Telemetria sem desfecho: {exc.orig}", flush=True)
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
                if confirmed_publications:
                    with engine.begin() as connection:
                        connection.execute(text("""
                            UPDATE pump_commands SET puback_at = :at WHERE command_id = :id
                        """), [
                            {"id": command_id, "at": at}
                            for command_id, at in confirmed_publications.items()
                        ])
                    confirmed_publications.clear()
                for mid, (_, expires_at) in list(awaiting_puback.items()):
                    if expires_at <= now:
                        del awaiting_puback[mid]
                if time.monotonic() >= next_alert_check:
                    with engine.begin() as connection:
                        check_missing_data(connection, now)
                    next_alert_check = time.monotonic() + 1
                if invalidate_pending:
                    with engine.begin() as connection:
                        invalidate_controls(connection)
                with engine.begin() as connection:
                    expire_commands(connection, now)
                if connected and safety_offs_pending:
                    with engine.begin() as connection:
                        queue_safety_offs(connection, now)
                commands = []
                if connected:
                    with engine.begin() as connection:
                        queue_alert_recoveries(connection, now)
                        commands = pending_commands(connection, now)
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
                        awaiting_puback[info.mid] = (command.command_id, command.expires_at)
            except SQLAlchemyError as exc:
                database_failed(exc)
            except (RuntimeError, OSError) as exc:
                print(f"Comando sem confirmação de transporte: {exc}", flush=True)
    finally:
        connector.shutdown(wait=True, cancel_futures=True)
        client.disconnect()
        for writer in live_writers:
            writer.shutdown(wait=True, cancel_futures=True)
        history.shutdown(wait=True, cancel_futures=True)
        engine.dispose()


if __name__ == "__main__":
    main()
