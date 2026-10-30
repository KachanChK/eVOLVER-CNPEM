from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter, ValidationError

from evolver_contracts.models import (
    JSON_SCHEMA_DIALECT,
    CommandPayload,
    CommandResultPayload,
    TelemetryAcknowledgement,
    TelemetryEvent,
    TelemetryRejection,
    schema_sources,
)

CONTRACTS_ROOT = Path(__file__).resolve().parents[1] / "src" / "evolver_contracts"
FIXTURES_ROOT = Path(__file__).with_name("fixtures")
COMMAND_ADAPTER = TypeAdapter(CommandPayload)
COMMAND_RESULT_ADAPTER = TypeAdapter(CommandResultPayload)

VERSIONED_CASES = [
    ("telemetry.schema.json", TelemetryEvent, "valid/telemetry-temperature.json"),
    ("telemetry-ack.schema.json", TelemetryAcknowledgement, "valid/telemetry-ack-persisted.json"),
    (
        "telemetry-rejection.schema.json",
        TelemetryRejection,
        "valid/telemetry-rejection-quarantined.json",
    ),
    ("command.schema.json", COMMAND_ADAPTER, "valid/command-temperature-setpoint.json"),
    ("command-result.schema.json", COMMAND_RESULT_ADAPTER, "valid/command-result-executed.json"),
]


def load_json(relative_path: str) -> dict[str, Any]:
    return json.loads((FIXTURES_ROOT / relative_path).read_text(encoding="utf-8"))


VALID_CASES = [
    ("telemetry.schema.json", TelemetryEvent, "valid/telemetry-temperature.json"),
    ("telemetry-ack.schema.json", TelemetryAcknowledgement, "valid/telemetry-ack-persisted.json"),
    ("telemetry-ack.schema.json", TelemetryAcknowledgement, "valid/telemetry-ack-duplicate.json"),
    (
        "telemetry-rejection.schema.json",
        TelemetryRejection,
        "valid/telemetry-rejection-quarantined.json",
    ),
    ("command.schema.json", COMMAND_ADAPTER, "valid/command-temperature-setpoint.json"),
    ("command.schema.json", COMMAND_ADAPTER, "valid/command-pump-turn-on.json"),
    ("command-result.schema.json", COMMAND_RESULT_ADAPTER, "valid/command-result-received.json"),
    ("command-result.schema.json", COMMAND_RESULT_ADAPTER, "valid/command-result-executed.json"),
    ("command-result.schema.json", COMMAND_RESULT_ADAPTER, "valid/command-result-rejected.json"),
    (
        "command-result.schema.json",
        COMMAND_RESULT_ADAPTER,
        "valid/command-result-expired-during-disconnection.json",
    ),
]

INVALID_CASES = [
    ("telemetry.schema.json", TelemetryEvent, "invalid/telemetry-missing-measurement-type.json"),
    ("command.schema.json", COMMAND_ADAPTER, "invalid/command-pump-out-of-range.json"),
    (
        "command-result.schema.json",
        COMMAND_RESULT_ADAPTER,
        "invalid/command-result-rejected-missing-reason.json",
    ),
    (
        "command.schema.json",
        COMMAND_ADAPTER,
        "semantic-invalid/command-expired-at-creation.json",
    ),
    ("telemetry.schema.json", TelemetryEvent, "invalid/telemetry-missing-schema-version.json"),
    ("telemetry.schema.json", TelemetryEvent, "invalid/telemetry-unsupported-schema-version.json"),
]


def validate_with_model(adapter: type | TypeAdapter[Any], payload: dict[str, Any]) -> Any:
    if isinstance(adapter, TypeAdapter):
        return adapter.validate_python(payload)
    return adapter.model_validate(payload)


@pytest.mark.parametrize(("schema_name", "adapter", "fixture"), VALID_CASES)
def test_valid_examples_match_schema_and_model(
    schema_name: str,
    adapter: type | TypeAdapter[Any],
    fixture: str,
) -> None:
    payload = load_json(fixture)
    schema = schema_sources()[schema_name]

    assert Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(payload)
    validate_with_model(adapter, payload)


@pytest.mark.parametrize(("schema_name", "adapter", "fixture"), INVALID_CASES)
def test_invalid_examples_are_rejected(
    schema_name: str,
    adapter: type | TypeAdapter[Any],
    fixture: str,
) -> None:
    payload = load_json(fixture)
    schema = schema_sources()[schema_name]

    if fixture.startswith("semantic-invalid/"):
        assert Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(payload)
    else:
        assert not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(payload)

    with pytest.raises(ValidationError):
        validate_with_model(adapter, payload)


def test_expired_command_is_rejected_with_the_same_command_id() -> None:
    command = COMMAND_ADAPTER.validate_python(
        load_json("semantic-invalid/command-expired-during-disconnection.json"),
    )
    result = COMMAND_RESULT_ADAPTER.validate_python(
        load_json("valid/command-result-expired-during-disconnection.json"),
    )

    assert command.is_expired_at(datetime.fromisoformat("2026-10-27T13:12:00+00:00"))
    assert result.command_id == command.command_id
    assert result.status == "rejected"
    assert result.reason_code == "expired"


def test_committed_schemas_are_generated_from_runtime_models() -> None:
    for filename, generated_schema in schema_sources().items():
        committed_schema = json.loads(
            (CONTRACTS_ROOT / "schemas" / filename).read_text(encoding="utf-8"),
        )
        assert committed_schema == generated_schema


def test_schemas_declare_dialect() -> None:
    for schema in schema_sources().values():
        assert schema["$schema"] == JSON_SCHEMA_DIALECT


@pytest.mark.parametrize(("schema_name", "adapter", "fixture"), VERSIONED_CASES)
def test_schema_version_is_required_for_every_message(
    schema_name: str,
    adapter: type | TypeAdapter[Any],
    fixture: str,
) -> None:
    payload = load_json(fixture)
    payload.pop("schema_version")
    schema = schema_sources()[schema_name]

    assert not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(payload)
    with pytest.raises(ValidationError):
        validate_with_model(adapter, payload)
