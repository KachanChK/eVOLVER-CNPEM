from __future__ import annotations

import os
from pathlib import Path

import pytest
from evolver_simulator.config import SimulatorSettings
from pydantic import ValidationError


def make_settings(**overrides: object) -> SimulatorSettings:
    values: dict[str, object] = {"mqtt_simulator_password": "local-secret", **overrides}
    return SimulatorSettings(_env_file=None, **values)


def test_defaults_match_mosquitto_acl_identity_and_topic() -> None:
    settings = make_settings()

    assert settings.equipment_id == "evolver-sim-01"
    assert settings.mqtt_username == settings.equipment_id
    assert settings.telemetry_topic == "evolver/v1/evolver-sim-01/telemetry"
    assert settings.seed is None
    assert (settings.ph_baseline, settings.temperature_baseline) == (7.0, 37.0)


def test_password_is_required() -> None:
    with pytest.raises(ValidationError):
        SimulatorSettings(_env_file=None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("od_baseline", -0.1),
        ("od_variation", -0.1),
        ("od_noise", -0.1),
        ("od_noise", 0.2),
        ("ph_variation", -0.1),
        ("ph_noise", -0.1),
        ("temperature_variation", -0.1),
        ("temperature_noise", -0.1),
        ("max_messages", 0),
        ("mqtt_protocol_version", 4),
        ("mqtt_host", "  "),
        ("mqtt_simulator_password", "  "),
        ("pause_after_messages", 0),
        ("pause_seconds", 0),
        ("fail_after_messages", 0),
    ],
)
def test_invalid_configuration_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


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


def test_independent_broker_examples_match_versioned_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    for key in list(os.environ):
        if key.startswith(("MQTT_", "SIMULATOR_")):
            monkeypatch.delenv(key)
    settings = SimulatorSettings(_env_file=root / "simulator" / ".env.example")
    broker_env = (root / "mqtt" / ".env.example").read_text(encoding="utf-8")
    acl = (root / "mqtt" / "acl").read_text(encoding="utf-8")
    assert f"MQTT_SIMULATOR_PASSWORD={settings.mqtt_simulator_password}" in broker_env
    simulator_acl = acl.split(f"user {settings.mqtt_username}\n", 1)[1].split("\nuser ", 1)[0]
    assert f"topic write {settings.telemetry_topic}" in simulator_acl
    assert "topic write evolver/dev/evolver-sim-01/active-vials/request" in simulator_acl
    assert "topic read evolver/dev/evolver-sim-01/active-vials/response" in simulator_acl
    assert "topic read evolver/v1/+/telemetry" in acl
