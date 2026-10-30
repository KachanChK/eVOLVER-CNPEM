"""MQTT loop of the ingestion process.

`process_message` holds the decision for one message and only returns the reply
after the database commit; `run` subscribes to telemetry and publishes that reply.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiomqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from sqlalchemy.exc import SQLAlchemyError

from evolver.ingestion.config import TELEMETRY_SUBSCRIPTION, IngestionSettings
from evolver.ingestion.persistence import (
    Duplicate,
    Persisted,
    Quarantined,
    StoreOutcome,
    TelemetryStore,
)
from evolver.ingestion.validation import (
    AcceptedTelemetry,
    RejectedTelemetry,
    UncorrelatedTelemetry,
    validate_telemetry,
)
from evolver_contracts import TelemetryAcknowledgement, TelemetryRejection

logger = logging.getLogger(__name__)

type Clock = Callable[[], datetime]


@dataclass(frozen=True)
class Reply:
    topic: str
    message: TelemetryAcknowledgement | TelemetryRejection

    def payload(self) -> str:
        return self.message.model_dump_json()


def ack_topic(equipment_id: str) -> str:
    return f"evolver/v1/{equipment_id}/telemetry/ack"


def rejection_topic(equipment_id: str) -> str:
    return f"evolver/v1/{equipment_id}/telemetry/rejection"


def utc_now() -> datetime:
    return datetime.now(UTC)


def process_message(
    topic: str,
    payload: bytes,
    store: TelemetryStore,
    *,
    max_clock_skew: timedelta,
    clock: Clock = utc_now,
) -> Reply | None:
    """Validate and store one message; database errors propagate without a reply."""
    received_at = clock()
    result = validate_telemetry(
        topic, payload, now=received_at, max_clock_skew=max_clock_skew
    )
    if isinstance(result, UncorrelatedTelemetry):
        logger.error("mensagem descartada em %s: %s", result.topic, result.detail)
        return None

    outcome: StoreOutcome
    if isinstance(result, AcceptedTelemetry):
        outcome = store.persist(result, received_at=received_at)
    else:
        outcome = store.quarantine(result, received_at=received_at)
    return _reply(result, outcome, replied_at=clock())


def _reply(
    result: AcceptedTelemetry | RejectedTelemetry, outcome: StoreOutcome, *, replied_at: datetime
) -> Reply:
    # Respostas vão ao tópico autenticado de origem, não ao equipment_id do payload.
    equipment_id = result.topic_equipment_id
    if isinstance(outcome, Persisted | Duplicate):
        status = "persisted" if isinstance(outcome, Persisted) else "duplicate"
        logger.info("evento %s %s", outcome.event_id, status)
        return Reply(
            ack_topic(equipment_id),
            TelemetryAcknowledgement(
                schema_version="1.0",
                event_id=outcome.event_id,
                equipment_id=equipment_id,
                status=status,
                acknowledged_at=replied_at,
            ),
        )
    assert isinstance(outcome, Quarantined)
    logger.warning(
        "evento %s em quarentena: %s (%s)", outcome.event_id, outcome.reason_code, outcome.detail
    )
    return Reply(
        rejection_topic(equipment_id),
        TelemetryRejection(
            schema_version="1.0",
            event_id=outcome.event_id,
            equipment_id=equipment_id,
            reason_code=outcome.reason_code,
            disposition="quarantined",
            detail=outcome.detail,
            rejected_at=replied_at,
        ),
    )


def _client(settings: IngestionSettings) -> aiomqtt.Client:
    properties = Properties(PacketTypes.CONNECT)
    properties.SessionExpiryInterval = settings.mqtt_session_expiry_seconds
    return aiomqtt.Client(
        settings.mqtt_host,
        settings.mqtt_port,
        username=settings.mqtt_username,
        password=settings.mqtt_password,
        identifier=settings.mqtt_client_id,
        protocol=aiomqtt.ProtocolVersion.V5,
        clean_start=False,
        properties=properties,
    )


async def run(settings: IngestionSettings, store: TelemetryStore) -> None:
    """Consume telemetry until cancelled, reconnecting after broker failures."""
    while True:
        try:
            async with _client(settings) as client:
                await client.subscribe(TELEMETRY_SUBSCRIPTION, qos=1)
                logger.info(
                    "ingestão conectada a %s:%s, assinando %s",
                    settings.mqtt_host,
                    settings.mqtt_port,
                    TELEMETRY_SUBSCRIPTION,
                )
                async for message in client.messages:
                    await _handle(client, settings, store, message)
        except aiomqtt.MqttError as error:
            logger.warning(
                "conexão MQTT perdida (%s); nova tentativa em %.0f s",
                error,
                settings.reconnect_interval_seconds,
            )
            await asyncio.sleep(settings.reconnect_interval_seconds)


async def _handle(
    client: aiomqtt.Client,
    settings: IngestionSettings,
    store: TelemetryStore,
    message: aiomqtt.Message,
) -> None:
    payload = message.payload
    if isinstance(payload, str):
        payload = payload.encode()
    elif not isinstance(payload, bytes | bytearray):
        payload = b"" if payload is None else str(payload).encode()
    try:
        # SQLAlchemy é síncrono; a thread mantém o keepalive MQTT durante a transação.
        reply = await asyncio.to_thread(
            process_message,
            message.topic.value,
            bytes(payload),
            store,
            max_clock_skew=settings.max_clock_skew,
        )
    except Exception as error:
        # Sem ACK: o produtor mantém o evento na fila e reenvia com o mesmo event_id.
        # Outros erros também não derrubam o loop, para uma mensagem não travar as demais.
        kind = "gravar" if isinstance(error, SQLAlchemyError) else "processar"
        logger.exception(
            "falha ao %s mensagem de %s; nenhuma confirmação enviada", kind, message.topic.value
        )
        return
    if reply is not None:
        await client.publish(reply.topic, reply.payload(), qos=1)
