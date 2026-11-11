"""Store the temporary simulator's temperature messages in PostgreSQL."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from evolver_contracts.pilot import (
    ACTIVE_VIALS_REQUEST,
    ACTIVE_VIALS_RESPONSE,
    EQUIPMENT_ID,
    AllocationRequest,
    AllocationResponse,
    TemperatureMessage,
)
from paho.mqtt import client as mqtt
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def active_vials(engine: Engine, payload: bytes) -> AllocationResponse:
    request = AllocationRequest.model_validate_json(payload)
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text("""
                SELECT e.vial_id, e.id AS experiment_id
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


def store_message(engine: Engine, topic: str, payload: bytes) -> str:
    message = TemperatureMessage.model_validate_json(payload)
    if topic != f"evolver/dev/{message.equipment_id}/telemetry":
        raise ValueError("equipment_id does not match the MQTT topic")
    with engine.begin() as connection:
        allocation = connection.execute(
            text("""
                SELECT e.id
                FROM experiments e JOIN vials v ON v.vial_id = e.vial_id
                WHERE e.id = :experiment_id AND e.vial_id = :vial_id
                  AND v.equipment_id = :equipment_id
                  AND e.started_at <= :generated_at
                  AND (e.ended_at IS NULL OR :generated_at < e.ended_at)
                  AND :generated_at <= clock_timestamp()
                FOR SHARE OF e
            """),
            message.model_dump(),
        ).scalar_one_or_none()
        if allocation is None:
            raise ValueError("não havia essa alocação para o vial no horário da leitura")
        result = connection.execute(
            text("""
                INSERT INTO temperature_readings
                    (event_id, generated_at, received_at, vial_id,
                     experiment_id, temperature_celsius)
                VALUES (:event_id, :generated_at, :received_at, :vial_id, :experiment_id, :value)
                ON CONFLICT (event_id, generated_at) DO NOTHING
            """),
            {
                **message.model_dump(),
                "received_at": datetime.now(UTC),
            },
        )
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
        client.subscribe([("evolver/dev/+/telemetry", 1), (ACTIVE_VIALS_REQUEST, 1)])
        print("Ingestão MQTT pronta para temperaturas.", flush=True)

    def on_message(client, userdata, message) -> None:
        del userdata
        try:
            if message.topic == ACTIVE_VIALS_REQUEST:
                response = active_vials(engine, message.payload)
                client.publish(ACTIVE_VIALS_RESPONSE, response.model_dump_json(), qos=1)
                return
            status = store_message(engine, message.topic, message.payload)
            print(f"Temperatura {status}: {message.topic}", flush=True)
        except Exception as exc:
            print(f"Mensagem não gravada: {exc}", flush=True)

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(os.getenv("MQTT_HOST", "127.0.0.1"), int(os.getenv("MQTT_PORT", "1883")))
        client.loop_forever()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
