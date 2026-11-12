from __future__ import annotations

import os
import sys
import threading
from datetime import UTC, datetime
from uuid import uuid4

from evolver_contracts.pilot import (
    ACTIVE_VIALS_REQUEST,
    ACTIVE_VIALS_RESPONSE,
    EQUIPMENT_ID,
    TELEMETRY_TOPIC,
    ActiveVial,
    AllocationRequest,
    AllocationResponse,
    TemperatureMessage,
)
from paho.mqtt import client as mqtt

TIMEOUT_SECONDS = 5


def build_message(
    allocation: ActiveVial, generated_at: datetime | None = None
) -> TemperatureMessage:
    return TemperatureMessage(
        **allocation.model_dump(),
        equipment_id=EQUIPMENT_ID,
        event_id=uuid4(),
        measurement="temperature",
        value=37.0,
        unit="celsius",
        generated_at=generated_at or datetime.now(UTC),
    )


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
    subscribed = threading.Event()
    received = threading.Event()
    request = AllocationRequest(request_id=uuid4())
    response: AllocationResponse | None = None
    connection_error: list[str] = []
    subscription_error: list[str] = []
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

    def on_subscribe(client, userdata, mid, reason_codes, properties) -> None:
        subscription_error.extend(str(code) for code in reason_codes if code.is_failure)
        subscribed.set()

    def on_message(client, userdata, message) -> None:
        nonlocal response
        if message.topic != ACTIVE_VIALS_RESPONSE or message.retain or received.is_set():
            return
        try:
            candidate = AllocationResponse.model_validate_json(message.payload)
        except ValueError:
            return
        if candidate.request_id == request.request_id:
            response = candidate
            received.set()

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
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    client.on_publish = on_publish
    loop_started = False

    def publish(topic: str, payload: str) -> None:
        publication = client.publish(topic, payload, qos=1, retain=False)
        publication.wait_for_publish(timeout=TIMEOUT_SECONDS)
        if not publication.is_published():
            raise TimeoutError("PUBACK não recebido em 5 segundos")
        if publish_error:
            raise ConnectionError(f"broker rejeitou a publicação: {publish_error[0]}")

    try:
        client.connect(host, port, keepalive=60)
        client.loop_start()
        loop_started = True

        if not connected.wait(TIMEOUT_SECONDS):
            raise TimeoutError("o broker não respondeu à conexão em 5 segundos")
        if connection_error:
            raise ConnectionError(f"conexão recusada pelo broker: {connection_error[0]}")

        print(f"Conectado ao MQTT em {host}:{port} como {EQUIPMENT_ID}.")
        result, _ = client.subscribe(ACTIVE_VIALS_RESPONSE, qos=1)
        if result != mqtt.MQTT_ERR_SUCCESS or not subscribed.wait(TIMEOUT_SECONDS):
            raise ConnectionError("não foi possível assinar a resposta de vials ativos")
        if subscription_error:
            raise ConnectionError(f"assinatura recusada: {subscription_error[0]}")
        publish(ACTIVE_VIALS_REQUEST, request.model_dump_json())
        if not received.wait(TIMEOUT_SECONDS) or response is None:
            raise TimeoutError("a ingestão não respondeu à consulta de vials ativos")

        if not response.vials:
            print("Nenhum experimento ativo. Nenhuma temperatura enviada.")
        for allocation in response.vials:
            message = build_message(allocation)
            publish(TELEMETRY_TOPIC, message.model_dump_json())
            print(f"Vial {allocation.vial_id}: PUBACK recebido para {message.event_id}.")
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
