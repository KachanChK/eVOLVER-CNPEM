from __future__ import annotations

import os
from pathlib import Path

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
    assert settings.vial_ids == ("1",)
    assert settings.seed is None
    assert (settings.ph_baseline, settings.temperature_baseline) == (7.0, 37.0)


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
        ("ph_variation", -0.1),
        ("ph_noise", -0.1),
        ("temperature_variation", -0.1),
        ("temperature_noise", -0.1),
        ("max_messages", 0),
        ("mqtt_protocol_version", 4),
        ("mqtt_host", "  "),
        ("mqtt_simulator_password", "  "),
        ("vial_ids_csv", ""),
        ("vial_id", 0),
        ("vial_ids_csv", "1,1"),
        ("vial_ids_csv", "vial-01"),
        ("vial_ids_csv", "01"),
        ("vial_ids_csv", "9223372036854775808"),
        ("pause_after_messages", 0),
        ("pause_seconds", 0),
        ("fail_after_messages", 0),
        ("vial_ids_csv", ",".join(str(index + 1) for index in range(MAX_VIALS + 1))),
    ],
)
def test_invalid_configuration_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_vial_ids_are_trimmed_and_keep_declared_order() -> None:
    settings = make_settings(vial_ids_csv=" 2, 1 ")

    assert settings.vial_ids == ("2", "1")


def test_vial_id_matches_the_database_setting() -> None:
    assert make_settings(vial_id=42).vial_ids == ("42",)


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
        if key.startswith(("MQTT_", "SIMULATOR_")) or key == "VIAL_ID":
            monkeypatch.delenv(key)
    settings = SimulatorSettings(_env_file=root / "simulator" / ".env.example")
    broker_env = (root / "mqtt" / ".env.example").read_text(encoding="utf-8")
    acl = (root / "mqtt" / "acl").read_text(encoding="utf-8")
    assert f"MQTT_SIMULATOR_PASSWORD={settings.mqtt_simulator_password}" in broker_env
    simulator_acl = acl.split(f"user {settings.mqtt_username}\n", 1)[1].split("\nuser ", 1)[0]
    assert f"topic write {settings.telemetry_topic}" in simulator_acl
    assert f"topic write {settings.temperature_topic}" in simulator_acl
    assert "topic read evolver/v1/+/telemetry" in acl
