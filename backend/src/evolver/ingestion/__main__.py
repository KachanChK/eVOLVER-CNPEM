"""Store versioned simulator telemetry and answer active vial queries."""

from __future__ import annotations

import math
import os
import time
from datetime import UTC, datetime

from evolver_contracts.models import CommandResultPayload, TelemetryEvent
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

from .control import (
    command_is_current,
    consider_od,
    expire_commands,
    invalidate_controls,
    pending_commands,
    queue_safety_offs,
    record_result,
)


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


def store_v1_message(engine: Engine, topic: str, payload: bytes) -> str:
    """Associate a simulator reading with the vial allocation at generation time."""
    message = TelemetryEvent.model_validate_json(payload)
    if (
        message.equipment_id != EQUIPMENT_ID
        or topic != f"evolver/v1/{message.equipment_id}/telemetry"
    ):
        raise ValueError("equipamento não corresponde ao tópico")
    if not message.vial_id.isascii() or not message.vial_id.isdecimal():
        raise ValueError("vial inválido")
    vial_id = int(message.vial_id)
    if not 1 <= vial_id <= 12 or not math.isfinite(message.value):
        raise ValueError("vial ou valor inválido")
    experiment_id = message.experiment_run_id
    if experiment_id is not None and (
        not experiment_id.isascii()
        or not experiment_id.isdecimal()
        or not 1 <= int(experiment_id) <= 2**63 - 1
    ):
        raise ValueError("experimento inválido")
    params = {
        "vial_id": vial_id,
        "equipment_id": message.equipment_id,
        "generated_at": message.generated_at,
        "received_at": None,
        "event_id": message.event_id,
        "value": message.value,
        "measurement_type": message.measurement_type,
        "producer_id": message.producer_id,
        "sequence": message.sequence,
        "expected_experiment_id": int(experiment_id) if experiment_id is not None else None,
    }
    with engine.begin() as connection:
        params["received_at"] = connection.scalar(text("SELECT clock_timestamp()"))
        allocation = connection.execute(
            text("""
            SELECT e.id FROM experiments e JOIN vials v ON v.vial_id = e.vial_id
            WHERE e.vial_id = :vial_id AND v.equipment_id = :equipment_id
              AND (CAST(:expected_experiment_id AS bigint) IS NULL
                   OR e.id = :expected_experiment_id)
              AND e.started_at <= :generated_at
              AND (e.ended_at IS NULL OR :generated_at < e.ended_at)
              AND :generated_at <= :received_at
            FOR UPDATE OF e
        """),
            params,
        ).scalar_one_or_none()
        if allocation is None:
            raise ValueError("não havia experimento ativo no horário da leitura")
        params["experiment_id"] = allocation
        if message.measurement_type == "temperature":
            statement = """INSERT INTO temperature_readings
                (event_id, generated_at, received_at, vial_id, experiment_id, temperature_celsius)
                VALUES (:event_id, :generated_at, :received_at, :vial_id, :experiment_id, :value)
                ON CONFLICT (event_id, generated_at) DO NOTHING"""
        elif message.measurement_type == "ph":
            statement = """INSERT INTO ph_readings
                (event_id, generated_at, received_at, vial_id, experiment_id, ph_value)
                VALUES (:event_id, :generated_at, :received_at, :vial_id, :experiment_id, :value)
                ON CONFLICT (event_id, generated_at) DO NOTHING"""
        else:
            statement = """INSERT INTO od_readings
                (event_id, generated_at, received_at, vial_id, experiment_id,
                 od_value, producer_id, sequence)
                VALUES (:event_id, :generated_at, :received_at, :vial_id, :experiment_id,
                        :value, :producer_id, :sequence)
                ON CONFLICT (event_id, generated_at) DO NOTHING"""
        result = connection.execute(text(statement), params)
        if result.rowcount and message.measurement_type == "od":
            consider_od(connection, params, params["received_at"])
    return "gravada" if result.rowcount else "duplicada"


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    password = os.environ["MQTT_INGESTION_PASSWORD"]
    engine = create_engine(database_url)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    client.username_pw_set("evolver-ingestion", password)

    def on_connect(client, userdata, flags, reason_code, properties) -> None:
        del userdata, flags, properties
        if reason_code.is_failure:
            raise ConnectionError(f"MQTT connection rejected: {reason_code}")
        with engine.begin() as connection:
            invalidate_controls(connection)
        client.subscribe(
            [
                ("evolver/v1/+/telemetry", 1),
                (ACTIVE_VIALS_REQUEST, 1),
                (f"evolver/v1/{EQUIPMENT_ID}/command-results", 1),
            ]
        )
        with engine.begin() as connection:
            queue_safety_offs(connection, datetime.now(UTC))
        print("Ingestão MQTT pronta para telemetria e comandos.", flush=True)

    def on_message(client, userdata, message) -> None:
        del userdata
        try:
            if message.topic == ACTIVE_VIALS_REQUEST:
                response = active_vials(engine, message.payload)
                client.publish(ACTIVE_VIALS_RESPONSE, response.model_dump_json(), qos=1)
                return
            if message.topic == f"evolver/v1/{EQUIPMENT_ID}/command-results":
                result = TypeAdapter(CommandResultPayload).validate_json(message.payload)
                if result.equipment_id != EQUIPMENT_ID:
                    raise ValueError("equipamento não corresponde ao resultado")
                with engine.begin() as connection:
                    record_result(connection, result)
                return
            status = store_v1_message(engine, message.topic, message.payload)
            print(f"Medição {status}: {message.topic}", flush=True)
        except Exception as exc:
            print(f"Mensagem não gravada: {exc}", flush=True)

    client.on_connect = on_connect
    def on_disconnect(client, userdata, flags, reason_code, properties) -> None:
        del client, userdata, flags, reason_code, properties
        with engine.begin() as connection:
            invalidate_controls(connection)

    client.on_disconnect = on_disconnect
    client.on_message = on_message
    awaiting_puback = {}
    try:
        client.connect(os.getenv("MQTT_HOST", "127.0.0.1"), int(os.getenv("MQTT_PORT", "1883")))
        client.loop_start()
        while True:
            now = datetime.now(UTC)
            with engine.begin() as connection:
                expire_commands(connection, now)
                commands = pending_commands(connection, now) if client.is_connected() else []
            for command in commands:
                try:
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
                except (RuntimeError, OSError) as exc:
                    print(f"Comando sem confirmação de transporte: {exc}", flush=True)
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
            time.sleep(0.2)
    finally:
        client.loop_stop()
        engine.dispose()


if __name__ == "__main__":
    main()
