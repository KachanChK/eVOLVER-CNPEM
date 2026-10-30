from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest

from evolver.ingestion.validation import (
    AcceptedTelemetry,
    RejectedTelemetry,
    UncorrelatedTelemetry,
    validate_telemetry,
)

from .payloads import NOW, TELEMETRY_TOPIC, encode, telemetry

SKEW = timedelta(minutes=5)


def validate(payload: bytes, topic: str = TELEMETRY_TOPIC):
    return validate_telemetry(topic, payload, now=NOW, max_clock_skew=SKEW)


def test_valid_od_is_accepted() -> None:
    payload = telemetry()

    result = validate(encode(payload))

    assert isinstance(result, AcceptedTelemetry)
    assert result.topic_equipment_id == "evolver-sim-01"
    assert result.event.event_id == UUID(payload["event_id"])
    assert result.event.measurement_type == "od"


def test_late_event_is_accepted_with_its_generation_time() -> None:
    generated_at = NOW - timedelta(hours=6)

    result = validate(encode(telemetry(generated_at=generated_at.isoformat())))

    assert isinstance(result, AcceptedTelemetry)
    assert result.event.generated_at == generated_at


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        ("evolver/v1/evolver-sim-01/commands", encode(telemetry())),
        ("evolver/v1/evolver-sim-01/telemetry", b"\xff\xfe"),
        ("evolver/v1/evolver-sim-01/telemetry", b"{not json"),
        ("evolver/v1/evolver-sim-01/telemetry", encode("[1, 2]")),
        ("evolver/v1/evolver-sim-01/telemetry", encode(telemetry(event_id=...))),
        ("evolver/v1/evolver-sim-01/telemetry", encode(telemetry(event_id="not-a-uuid"))),
    ],
    ids=["topic", "utf8", "json", "not-object", "missing-event-id", "invalid-event-id"],
)
def test_message_without_correlation_cannot_be_answered(topic: str, payload: bytes) -> None:
    assert isinstance(validate(payload, topic), UncorrelatedTelemetry)


@pytest.mark.parametrize(
    ("overrides", "reason_code", "detail_fragment"),
    [
        ({"measurement_type": ...}, "schema_invalid", "measurement_type"),
        ({"schema_version": ...}, "schema_invalid", "schema_version"),
        ({"schema_version": "2.0"}, "unsupported_schema_version", "2.0"),
        ({"value": "0.42"}, "schema_invalid", "value"),
        ({"value": True}, "schema_invalid", "value"),
        ({"sequence": -1}, "schema_invalid", "sequence"),
        ({"generated_at": "2026-11-04T12:00:00"}, "schema_invalid", "generated_at"),
        ({"vial_id": "vial 01"}, "schema_invalid", "vial_id"),
        ({"unexpected": 1}, "schema_invalid", "unexpected"),
        ({"equipment_id": "evolver-sim-02"}, "invalid_origin", "evolver-sim-02"),
        (
            {"generated_at": (NOW + timedelta(minutes=6)).isoformat()},
            "schema_invalid",
            "futuro",
        ),
    ],
)
def test_invalid_event_is_rejected_with_reason(
    overrides: dict, reason_code: str, detail_fragment: str
) -> None:
    payload = telemetry(**overrides)

    result = validate(encode(payload))

    assert isinstance(result, RejectedTelemetry)
    assert result.event_id == UUID(payload["event_id"])
    assert result.topic_equipment_id == "evolver-sim-01"
    assert result.reason_code == reason_code
    assert detail_fragment in result.detail


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_value_is_rejected(literal: str) -> None:
    raw = encode(telemetry(value=0.5)).decode().replace("0.5", literal)

    result = validate(raw.encode())

    assert isinstance(result, RejectedTelemetry)
    assert result.reason_code == "schema_invalid"


def test_detail_fits_the_rejection_contract() -> None:
    payload = telemetry(**{f"extra_{index}": index for index in range(40)})

    result = validate(encode(payload))

    assert isinstance(result, RejectedTelemetry)
    assert len(result.detail) <= 250
