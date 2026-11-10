"""Store the temporary simulator's temperature messages in PostgreSQL."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from paho.mqtt import client as mqtt
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat
from sqlalchemy import create_engine, text


class TemperatureMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_id: str
    event_id: UUID
    vial_id: int = Field(gt=0)
    measurement: Literal["temperature"]
    value: FiniteFloat
    unit: Literal["celsius"]
    generated_at: AwareDatetime


def store_message(engine, topic: str, payload: bytes) -> str:
    message = TemperatureMessage.model_validate(json.loads(payload))
    if topic != f"evolver/dev/{message.equipment_id}/telemetry":
        raise ValueError("equipment_id does not match the MQTT topic")
    with engine.begin() as connection:
        equipment_id = connection.execute(
            text("SELECT equipment_id FROM vials WHERE vial_id = :vial_id"),
            {"vial_id": message.vial_id},
        ).scalar_one_or_none()
        if equipment_id != message.equipment_id:
            raise ValueError("vial_id is unknown or belongs to another equipment")
        result = connection.execute(
            text("""
                INSERT INTO temperature_readings
                    (event_id, generated_at, received_at, vial_id, temperature_celsius)
                VALUES (:event_id, :generated_at, :received_at, :vial_id, :value)
                ON CONFLICT (event_id, generated_at) DO NOTHING
            """),
            {
                "event_id": message.event_id,
                "generated_at": message.generated_at,
                "received_at": datetime.now(UTC),
                "vial_id": message.vial_id,
                "value": message.value,
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
        client.subscribe("evolver/dev/+/telemetry", qos=1)
        print("Ingestão MQTT pronta para temperaturas.", flush=True)

    def on_message(client, userdata, message) -> None:
        del client, userdata
        try:
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
