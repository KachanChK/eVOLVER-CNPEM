from __future__ import annotations

import pytest
from evolver_simulator.config import MAX_VIALS, SimulatorSettings
from pydantic import ValidationError


def make_settings(**overrides: object) -> SimulatorSettings:
    values: dict[str, object] = {"mqtt_simulator_password": "local-secret", **overrides}
    return SimulatorSettings(_env_file=None, **values)


def test_defaults_match_mosquitto_acl_identity_and_topic() -> None:
    settings = make_settings()

    assert settings.equipment_id == "evolver-sim-01"
    assert settings.mqtt_username == settings.equipment_id
    assert settings.telemetry_topic == "evolver/v1/evolver-sim-01/telemetry"
    assert settings.vial_ids == ("vial-01", "vial-02", "vial-03")


def test_password_is_required() -> None:
    with pytest.raises(ValidationError):
        SimulatorSettings(_env_file=None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interval_seconds", 0),
        ("od_baseline", -0.1),
        ("od_variation", -0.1),
        ("od_noise", -0.1),
        ("od_noise", 0.2),
        ("max_messages", 0),
        ("mqtt_protocol_version", 4),
        ("mqtt_host", "  "),
        ("mqtt_simulator_password", "  "),
        ("vial_ids_csv", ""),
        ("vial_ids_csv", "vial-01,vial-01"),
        ("vial_ids_csv", "vial com espaco"),
        ("pause_after_messages", 0),
        ("pause_seconds", 0),
        ("fail_after_messages", 0),
        ("vial_ids_csv", ",".join(f"vial-{index}" for index in range(MAX_VIALS + 1))),
    ],
)
def test_invalid_configuration_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_vial_ids_are_trimmed_and_keep_declared_order() -> None:
    settings = make_settings(vial_ids_csv=" vial-b, vial-a ")

    assert settings.vial_ids == ("vial-b", "vial-a")


@pytest.mark.parametrize(
    "overrides",
    [
        {"pause_after_messages": 2},
        {"pause_seconds": 5},
        {
            "pause_after_messages": 2,
            "pause_seconds": 5,
            "fail_after_messages": 4,
        },
    ],
)
def test_incomplete_or_conflicting_scenario_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_pause_and_failure_scenarios_are_valid_separately() -> None:
    pause = make_settings(pause_after_messages=2, pause_seconds=5)
    failure = make_settings(fail_after_messages=3)

    assert (pause.pause_after_messages, pause.pause_seconds) == (2, 5.0)
    assert failure.fail_after_messages == 3
