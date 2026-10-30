"""OD crossing Mosquitto, the ingestion process and PostgreSQL."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import aiomqtt
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from evolver.db.models import Measurement, ProcessedEvent
from evolver.ingestion.config import IngestionSettings
from evolver.ingestion.persistence import TelemetryStore
from evolver.ingestion.service import run

from .conftest import register_source
from .payloads import telemetry

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# O ACL só permite ao simulador os tópicos do próprio equipment_id.
EQUIPMENT_ID = "evolver-sim-01"
TOPIC = f"evolver/v1/{EQUIPMENT_ID}/telemetry"
REPLY_TIMEOUT_SECONDS = 15


@pytest.fixture
def mqtt_settings() -> dict[str, Any]:
    host = os.getenv("EVOLVER_TEST_MQTT_HOST")
    if not host:
        pytest.skip("set EVOLVER_TEST_MQTT_HOST and the MQTT_*_PASSWORD values from .env")
    return {
        "host": host,
        "port": int(os.getenv("EVOLVER_TEST_MQTT_PORT", "1883")),
        "ingestion_password": os.environ["MQTT_INGESTION_PASSWORD"],
        "simulator_password": os.environ["MQTT_SIMULATOR_PASSWORD"],
    }


@pytest_asyncio.fixture
async def ingestion(mqtt_settings: dict[str, Any], database_url: str, store: TelemetryStore):
    settings = IngestionSettings(
        database_url=database_url,
        mqtt_password=mqtt_settings["ingestion_password"],
        mqtt_host=mqtt_settings["host"],
        mqtt_port=mqtt_settings["port"],
        # Identidade própria e sem sessão persistente para não disputar com a ingestão local.
        mqtt_client_id=f"evolver-ingestion-test-{uuid4().hex[:8]}",
        mqtt_session_expiry_seconds=0,
        reconnect_interval_seconds=0.5,
    )
    task = asyncio.create_task(run(settings, store))
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest_asyncio.fixture
async def producer(mqtt_settings: dict[str, Any]):
    async with aiomqtt.Client(
        mqtt_settings["host"],
        mqtt_settings["port"],
        username=EQUIPMENT_ID,
        password=mqtt_settings["simulator_password"],
        identifier=f"evolver-sim-01-test-{uuid4().hex[:8]}",
        protocol=aiomqtt.ProtocolVersion.V5,
    ) as client:
        await client.subscribe(f"{TOPIC}/ack", qos=1)
        await client.subscribe(f"{TOPIC}/rejection", qos=1)
        yield client


async def send_until_reply(
    client: aiomqtt.Client, payload: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Publish like Store and Forward: resend the same event until the application replies."""
    async with asyncio.timeout(REPLY_TIMEOUT_SECONDS):
        while True:
            await client.publish(TOPIC, json.dumps(payload), qos=1)
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(1):
                    async for message in client.messages:
                        reply = json.loads(message.payload)
                        if reply["event_id"] == payload["event_id"]:
                            return message.topic.value, reply


def stored(session_factory: sessionmaker[Session], event_id: str) -> tuple[int, str | None]:
    with session_factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Measurement)
            .where(Measurement.event_id == UUID(event_id))
        )
        outcome = session.scalar(
            select(ProcessedEvent.outcome).where(ProcessedEvent.event_id == UUID(event_id))
        )
    return count, outcome


async def test_od_crosses_broker_and_database_and_resend_is_duplicate(
    ingestion, producer: aiomqtt.Client, session_factory: sessionmaker[Session]
) -> None:
    source = register_source(session_factory, EQUIPMENT_ID)
    payload = telemetry(vial_id=source.vial_id, generated_at=datetime.now(UTC).isoformat())

    topic, first = await send_until_reply(producer, payload)
    _, second = await send_until_reply(producer, payload)

    assert topic == f"{TOPIC}/ack"
    assert first["status"] == "persisted"
    assert second["status"] == "duplicate"
    assert stored(session_factory, payload["event_id"]) == (1, "persisted")


async def test_invalid_message_is_rejected_without_blocking_the_next(
    ingestion, producer: aiomqtt.Client, session_factory: sessionmaker[Session]
) -> None:
    source = register_source(session_factory, EQUIPMENT_ID)
    invalid = telemetry(vial_id=source.vial_id, measurement_type=...)
    valid = telemetry(vial_id=source.vial_id, generated_at=datetime.now(UTC).isoformat())

    rejection_topic, rejection = await send_until_reply(producer, invalid)
    ack_topic, ack = await send_until_reply(producer, valid)

    assert rejection_topic == f"{TOPIC}/rejection"
    assert rejection["reason_code"] == "schema_invalid"
    assert rejection["disposition"] == "quarantined"
    assert stored(session_factory, invalid["event_id"]) == (0, "quarantined")
    assert ack_topic == f"{TOPIC}/ack"
    assert stored(session_factory, valid["event_id"]) == (1, "persisted")
