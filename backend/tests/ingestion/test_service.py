from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

from evolver.ingestion.config import IngestionSettings
from evolver.ingestion.persistence import Duplicate, Persisted, Quarantined
from evolver.ingestion.service import _handle, process_message

from .payloads import NOW, TELEMETRY_TOPIC, encode, telemetry

SKEW = timedelta(minutes=5)


class FakeStore:
    """Answers like TelemetryStore without a database; records what it was asked."""

    def __init__(self, outcome=None, error: Exception | None = None) -> None:
        self.outcome = outcome
        self.error = error
        self.calls: list[tuple[str, object]] = []

    def persist(self, accepted, *, received_at):
        self.calls.append(("persist", accepted))
        if self.error:
            raise self.error
        return self.outcome or Persisted(accepted.event.event_id)

    def quarantine(self, rejected, *, received_at):
        self.calls.append(("quarantine", rejected))
        if self.error:
            raise self.error
        return Quarantined(rejected.event_id, rejected.reason_code, rejected.detail)


def process(payload: bytes, store: FakeStore):
    return process_message(
        TELEMETRY_TOPIC, payload, store, max_clock_skew=SKEW, clock=lambda: NOW
    )


def test_persisted_event_is_acknowledged_on_the_origin_topic() -> None:
    payload = telemetry()
    store = FakeStore()

    reply = process(encode(payload), store)

    assert reply.topic == "evolver/v1/evolver-sim-01/telemetry/ack"
    assert reply.message.status == "persisted"
    assert reply.message.event_id == UUID(payload["event_id"])
    assert json.loads(reply.payload())["schema_version"] == "1.0"


def test_duplicate_is_acknowledged_as_duplicate() -> None:
    payload = telemetry()
    store = FakeStore(outcome=Duplicate(UUID(payload["event_id"])))

    reply = process(encode(payload), store)

    assert reply.message.status == "duplicate"


def test_rejected_event_is_quarantined_and_answered_with_rejection() -> None:
    payload = telemetry(equipment_id="evolver-sim-02")
    store = FakeStore()

    reply = process(encode(payload), store)

    assert [call for call, _ in store.calls] == ["quarantine"]
    assert reply.topic == "evolver/v1/evolver-sim-01/telemetry/rejection"
    assert reply.message.reason_code == "invalid_origin"
    assert reply.message.disposition == "quarantined"


def test_uncorrelated_message_is_not_stored_or_answered() -> None:
    store = FakeStore()

    assert process(b"{broken", store) is None
    assert store.calls == []


def test_database_failure_produces_no_reply() -> None:
    store = FakeStore(error=OperationalError("COMMIT", {}, Exception("connection lost")))

    with pytest.raises(OperationalError):
        process(encode(telemetry()), store)


class FakeClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, int]] = []

    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        self.published.append((topic, payload, qos))


def handle(store: FakeStore, payload: bytes) -> FakeClient:
    client = FakeClient()
    settings = IngestionSettings(database_url="unused", mqtt_password="unused")
    message = SimpleNamespace(topic=SimpleNamespace(value=TELEMETRY_TOPIC), payload=payload)
    asyncio.run(_handle(client, settings, store, message))
    return client


def test_mqtt_handler_publishes_reply_with_qos_1() -> None:
    # _handle usa o relógio real; o evento precisa ser do presente.
    client = handle(FakeStore(), encode(telemetry(generated_at=datetime.now(UTC).isoformat())))

    [(topic, payload, qos)] = client.published
    assert topic.endswith("/telemetry/ack")
    assert json.loads(payload)["status"] == "persisted"
    assert qos == 1


@pytest.mark.parametrize(
    "error",
    [OperationalError("COMMIT", {}, Exception("connection lost")), RuntimeError("bug")],
    ids=["database", "unexpected"],
)
def test_mqtt_handler_survives_failure_without_confirming(error: Exception) -> None:
    client = handle(FakeStore(error=error), encode(telemetry()))

    assert client.published == []
