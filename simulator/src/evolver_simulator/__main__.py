from __future__ import annotations

import json
import os
import sys
import threading
from datetime import UTC, datetime

from paho.mqtt import client as mqtt

EQUIPMENT_ID = "evolver-sim-01"
TOPIC = f"evolver/dev/{EQUIPMENT_ID}/telemetry"
TIMEOUT_SECONDS = 5


def build_message(generated_at: datetime | None = None) -> dict[str, str | float]:
    timestamp = generated_at or datetime.now(UTC)
    return {
        "equipment_id": EQUIPMENT_ID,
        "measurement": "temperature",
        "value": 37.0,
        "unit": "celsius",
        "generated_at": timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }


def main() -> int:
    host = os.getenv("MQTT_HOST", "127.0.0.1")
    password = os.getenv("MQTT_SIMULATOR_PASSWORD")

    if not password:
        print("Erro: defina MQTT_SIMULATOR_PASSWORD no ambiente.", file=sys.stderr)
        return 1

    try:
        port = int(os.getenv("MQTT_PORT", "1883"))
    except ValueError:
        print("Erro: MQTT_PORT deve ser um número inteiro.", file=sys.stderr)
        return 1

    connected = threading.Event()
    connection_error: list[str] = []
    publish_error: list[str] = []

    def on_connect(
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        del client, userdata, flags, properties
        if reason_code.is_failure:
            connection_error.append(str(reason_code))
        connected.set()

    def on_publish(
        client: mqtt.Client,
        userdata: object,
        mid: int,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties,
    ) -> None:
        del client, userdata, mid, properties
        if reason_code.is_failure:
            publish_error.append(str(reason_code))

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=EQUIPMENT_ID,
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set(EQUIPMENT_ID, password)
    client.on_connect = on_connect
    client.on_publish = on_publish
    loop_started = False

    try:
        client.connect(host, port, keepalive=60)
        client.loop_start()
        loop_started = True

        if not connected.wait(TIMEOUT_SECONDS):
            raise TimeoutError("o broker não respondeu à conexão em 5 segundos")
        if connection_error:
            raise ConnectionError(f"conexão recusada pelo broker: {connection_error[0]}")

        print(f"Conectado ao MQTT em {host}:{port} como {EQUIPMENT_ID}.")
        payload = json.dumps(build_message(), ensure_ascii=False, separators=(",", ":"))
        publication = client.publish(TOPIC, payload, qos=1, retain=False)
        publication.wait_for_publish(timeout=TIMEOUT_SECONDS)
        if not publication.is_published():
            raise TimeoutError("PUBACK não recebido em 5 segundos")
        if publish_error:
            raise ConnectionError(f"broker rejeitou a publicação: {publish_error[0]}")

        print(f"Mensagem enviada para {TOPIC}: {payload}")
        print("PUBACK recebido: o Mosquitto confirmou o transporte da publicação.")
        return 0
    except Exception as exc:
        print(f"Erro ao publicar temperatura: {exc}", file=sys.stderr)
        return 1
    finally:
        if loop_started:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    raise SystemExit(main())
