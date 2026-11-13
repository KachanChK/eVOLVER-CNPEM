from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from uuid import UUID

import pytest
from evolver_contracts.models import TelemetryEvent, schema_sources
from evolver_contracts.pilot import ActiveVial
from evolver_simulator.config import SimulatorSettings
from evolver_simulator.telemetry import SimulatedTelemetryGenerator
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

FIXED_TIME = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
FIXED_UUID = UUID("22222222-2222-4222-8222-222222222222")


def make_settings(**overrides: object) -> SimulatorSettings:
    values: dict[str, object] = {"mqtt_simulator_password": "local-secret", **overrides}
    return SimulatorSettings(_env_file=None, **values)


def allocations(*pairs: tuple[int, int]) -> list[ActiveVial]:
    return [ActiveVial(vial_id=vial, experiment_id=experiment) for vial, experiment in pairs]


def make_generator(
    settings: SimulatorSettings, vials: list[ActiveVial] | None = None
) -> SimulatedTelemetryGenerator:
    return SimulatedTelemetryGenerator(
        settings,
        vials if vials is not None else allocations((1, 41)),
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: FIXED_UUID,
    )


def test_same_seed_and_configuration_repeat_values_positions_and_sequence() -> None:
    settings = make_settings(seed=71)
    first = make_generator(settings, allocations((1, 41), (2, 42)))
    second = make_generator(settings, allocations((1, 41), (2, 42)))

    first_series = [first.next_event() for _ in range(12)]
    second_series = [second.next_event() for _ in range(12)]

    assert [
        (item.vial_id, item.measurement_type, item.value, item.sequence) for item in first_series
    ] == [
        (item.vial_id, item.measurement_type, item.value, item.sequence) for item in second_series
    ]


@pytest.mark.parametrize("kind", ["od", "ph", "temperature"])
def test_one_measurement_does_not_advance_other_random_streams(kind: str) -> None:
    settings = make_settings(seed=71)
    reference = make_generator(settings)
    with_extra_measurements = make_generator(settings)

    for other_kind in {"od", "ph", "temperature"} - {kind}:
        for cycle in range(10):
            with_extra_measurements._value_for(other_kind, 0, cycle)

    expected = [reference._value_for(kind, 0, cycle) for cycle in range(5)]
    actual = [with_extra_measurements._value_for(kind, 0, cycle) for cycle in range(5)]
    assert actual == expected


def test_measurement_trends_are_not_forced_to_move_in_lockstep() -> None:
    generator = make_generator(make_settings(seed=71, od_noise=0, ph_noise=0, temperature_noise=0))
    directions = {
        kind: [
            generator._value_for(kind, 0, cycle + 1) > generator._value_for(kind, 0, cycle)
            for cycle in range(24)
        ]
        for kind in ("od", "ph", "temperature")
    }
    assert any(len({directions[kind][cycle] for kind in directions}) > 1 for cycle in range(24))


def test_positions_cycle_in_declared_order_and_sequence_starts_at_zero() -> None:
    generator = make_generator(
        make_settings(od_noise=0, od_variation=0),
        allocations((3, 43), (1, 41), (2, 42)),
    )

    events = [generator.next_event() for _ in range(10)]

    assert [(event.vial_id, event.measurement_type) for event in events] == [
        ("3", "od"),
        ("3", "ph"),
        ("3", "temperature"),
        ("1", "od"),
        ("1", "ph"),
        ("1", "temperature"),
        ("2", "od"),
        ("2", "ph"),
        ("2", "temperature"),
        ("3", "od"),
    ]
    assert [event.sequence for event in events] == list(range(10))


def test_active_experiment_id_is_included_for_each_vial() -> None:
    generator = make_generator(
        make_settings(),
        allocations((1, 41), (2, 42)),
    )
    events = [generator.next_event() for _ in range(6)]
    assert [event.experiment_run_id for event in events] == ["41"] * 3 + ["42"] * 3


def test_noise_stays_within_configured_range() -> None:
    settings = make_settings(
        od_baseline=0.5,
        od_variation=0,
        od_noise=0.01,
    )
    generator = SimulatedTelemetryGenerator(
        settings,
        allocations((1, 41)),
        rng=random.Random(9),
        clock=lambda: FIXED_TIME,
        uuid_factory=lambda: FIXED_UUID,
    )

    values = [
        event.value
        for event in (generator.next_event() for _ in range(300))
        if event.measurement_type == "od"
    ]

    assert all(0.49 <= value <= 0.51 for value in values)
    assert len(set(values)) > 1


@pytest.mark.parametrize(
    ("measurement_type", "baseline", "noise"),
    [
        ("ph", 7.0, 0.02),
        ("temperature", 37.0, 0.1),
    ],
)
def test_ph_and_temperature_noise_stay_within_configured_mock_range(
    measurement_type: str,
    baseline: float,
    noise: float,
) -> None:
    generator = make_generator(
        make_settings(
            od_variation=0,
            od_noise=0,
            ph_variation=0,
            ph_noise=0.02,
            temperature_variation=0,
            temperature_noise=0.1,
        ),
    )

    values = [
        event.value
        for event in (generator.next_event() for _ in range(90))
        if event.measurement_type == measurement_type
    ]

    assert all(baseline - noise <= value <= baseline + noise for value in values)
    assert len(set(values)) > 1


def test_event_contains_required_fields_and_matches_runtime_model_and_schema() -> None:
    generator = make_generator(make_settings())
    events = [generator.next_event() for _ in range(3)]
    event = events[0]
    payload = json.loads(event.model_dump_json())

    assert payload["schema_version"] == "1.0"
    assert payload["event_id"] == str(FIXED_UUID)
    assert payload["producer_id"] == "simulator-local-01"
    assert payload["equipment_id"] == "evolver-sim-01"
    assert payload["vial_id"] == "1"
    assert payload["measurement_type"] == "od"
    assert isinstance(payload["value"], float)
    assert payload["generated_at"] == "2026-10-29T12:00:00Z"
    assert payload["sequence"] == 0
    assert [item.measurement_type for item in events] == ["od", "ph", "temperature"]
    validator = Draft202012Validator(
        schema_sources()["telemetry.schema.json"],
        format_checker=FormatChecker(),
    )
    for generated_event in events:
        generated_payload = json.loads(generated_event.model_dump_json())
        validated_event = TelemetryEvent.model_validate_json(generated_event.model_dump_json())
        assert validated_event == generated_event
        assert validator.is_valid(generated_payload)


def test_naive_clock_value_is_rejected_by_shared_contract() -> None:
    generator = SimulatedTelemetryGenerator(
        make_settings(),
        allocations((1, 41)),
        clock=lambda: datetime(2026, 10, 29, 12, 0),
        uuid_factory=lambda: FIXED_UUID,
    )

    with pytest.raises(ValidationError):
        generator.next_event()
