from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from uuid import UUID

import pytest
from evolver_contracts.models import TelemetryEvent, schema_sources
from evolver_simulator.config import SimulatorSettings
from evolver_simulator.telemetry import OdTelemetryGenerator
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

FIXED_TIME = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
FIXED_UUID = UUID("22222222-2222-4222-8222-222222222222")


def make_settings(**overrides: object) -> SimulatorSettings:
    values: dict[str, object] = {"mqtt_simulator_password": "local-secret", **overrides}
    return SimulatorSettings(_env_file=None, **values)


def make_generator(settings: SimulatorSettings) -> OdTelemetryGenerator:
    return OdTelemetryGenerator(
        settings,
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: FIXED_UUID,
    )


def test_same_seed_and_configuration_repeat_values_positions_and_sequence() -> None:
    settings = make_settings(seed=71, vial_ids_csv="vial-a,vial-b")
    first = make_generator(settings)
    second = make_generator(settings)

    first_series = [first.next_event() for _ in range(12)]
    second_series = [second.next_event() for _ in range(12)]

    assert [(item.vial_id, item.value, item.sequence) for item in first_series] == [
        (item.vial_id, item.value, item.sequence) for item in second_series
    ]


def test_positions_cycle_in_declared_order_and_sequence_starts_at_zero() -> None:
    generator = make_generator(
        make_settings(vial_ids_csv="vial-c,vial-a,vial-b", od_noise=0, od_variation=0),
    )

    events = [generator.next_event() for _ in range(7)]

    assert [event.vial_id for event in events] == [
        "vial-c",
        "vial-a",
        "vial-b",
        "vial-c",
        "vial-a",
        "vial-b",
        "vial-c",
    ]
    assert [event.sequence for event in events] == list(range(7))


def test_noise_stays_within_configured_range() -> None:
    settings = make_settings(
        vial_ids_csv="vial-01",
        od_baseline=0.5,
        od_variation=0,
        od_noise=0.01,
    )
    generator = OdTelemetryGenerator(
        settings,
        rng=random.Random(9),
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: FIXED_UUID,
    )

    values = [generator.next_event().value for _ in range(100)]

    assert all(0.49 <= value <= 0.51 for value in values)
    assert len(set(values)) > 1


def test_event_contains_required_fields_and_matches_runtime_model_and_schema() -> None:
    event = make_generator(make_settings()).next_event()
    payload = json.loads(event.model_dump_json())

    assert payload["schema_version"] == "1.0"
    assert payload["event_id"] == str(FIXED_UUID)
    assert payload["producer_id"] == "simulator-local-01"
    assert payload["equipment_id"] == "evolver-sim-01"
    assert payload["vial_id"] == "vial-01"
    assert payload["measurement_type"] == "od"
    assert isinstance(payload["value"], float)
    assert payload["generated_at"] == "2026-10-29T12:00:00Z"
    assert payload["sequence"] == 0
    assert TelemetryEvent.model_validate_json(event.model_dump_json()) == event
    assert Draft202012Validator(
        schema_sources()["telemetry.schema.json"],
        format_checker=FormatChecker(),
    ).is_valid(payload)


def test_naive_clock_value_is_rejected_by_shared_contract() -> None:
    generator = OdTelemetryGenerator(
        make_settings(),
        clock=lambda: datetime(2026, 10, 29, 12, 0),
        uuid_factory=lambda: FIXED_UUID,
    )

    with pytest.raises(ValidationError):
        generator.next_event()
