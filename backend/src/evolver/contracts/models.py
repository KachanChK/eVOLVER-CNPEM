"""Contratos MQTT v1 do piloto simulado.

Os modelos Pydantic são a fonte de verdade em tempo de execução. Os JSON Schemas
versionados são gerados a partir deles por ``export_schemas.py`` para consumidores
que não usam Python.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

type Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"),
]
type ShortDetail = Annotated[str, StringConstraints(min_length=1, max_length=250)]
type SchemaVersion = Literal["1.0"]
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


class ContractModel(BaseModel):
    """Campos e comportamento compartilhados por todas as mensagens MQTT."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: SchemaVersion


class TelemetryEvent(ContractModel):
    event_id: UUID
    producer_id: Identifier
    equipment_id: Identifier
    vial_id: Identifier
    experiment_run_id: Identifier | None = None
    measurement_type: Literal["od", "ph", "temperature"]
    value: float
    generated_at: AwareDatetime
    sequence: NonNegativeInt


class TelemetryAcknowledgement(ContractModel):
    event_id: UUID
    equipment_id: Identifier
    status: Literal["persisted", "duplicate"]
    acknowledged_at: AwareDatetime


class TelemetryRejection(ContractModel):
    event_id: UUID
    equipment_id: Identifier
    reason_code: Literal[
        "schema_invalid",
        "unsupported_schema_version",
        "invalid_origin",
        "unknown_equipment",
        "unknown_vial",
    ]
    disposition: Literal["quarantined"]
    detail: ShortDetail | None = None
    rejected_at: AwareDatetime


class BaseCommand(ContractModel):
    command_id: UUID
    equipment_id: Identifier
    experiment_run_id: Identifier | None = None
    author_id: Identifier
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def expires_after_creation(self) -> BaseCommand:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self

    def is_expired_at(self, moment: datetime) -> bool:
        """Return whether the simulator must reject this command at ``moment``."""
        return moment >= self.expires_at


class TemperatureSetpointCommand(BaseCommand):
    target_type: Literal["temperature_setpoint"]
    vial_id: Identifier
    action: Literal["set"]
    setpoint: float


class PumpCommand(BaseCommand):
    target_type: Literal["pump"]
    pump_id: Literal[1, 2, 3]
    action: Literal["turn_on", "turn_off"]


type CommandPayload = Annotated[
    TemperatureSetpointCommand | PumpCommand,
    Field(discriminator="target_type"),
]


class BaseCommandResult(ContractModel):
    command_id: UUID
    equipment_id: Identifier
    simulated: Literal[True]
    reported_at: AwareDatetime
    detail: ShortDetail | None = None


class ReceivedCommandResult(BaseCommandResult):
    status: Literal["received"]


class ExecutedCommandResult(BaseCommandResult):
    status: Literal["executed"]


class RejectedCommandResult(BaseCommandResult):
    status: Literal["rejected"]
    reason_code: Literal[
        "expired",
        "unsupported_target",
        "unsupported_action",
        "invalid_payload",
    ]


class FailedCommandResult(BaseCommandResult):
    status: Literal["failed"]
    reason_code: Literal["simulation_error"]


type CommandResultPayload = Annotated[
    ReceivedCommandResult
    | ExecutedCommandResult
    | RejectedCommandResult
    | FailedCommandResult,
    Field(discriminator="status"),
]


def schema_sources() -> dict[str, dict]:
    """Return the committed JSON Schemas generated from the runtime models."""

    generated = {
        "telemetry.schema.json": TelemetryEvent.model_json_schema(),
        "telemetry-ack.schema.json": TelemetryAcknowledgement.model_json_schema(),
        "telemetry-rejection.schema.json": TelemetryRejection.model_json_schema(),
        "command.schema.json": TypeAdapter(CommandPayload).json_schema(),
        "command-result.schema.json": TypeAdapter(CommandResultPayload).json_schema(),
    }
    return {
        filename: {"$schema": JSON_SCHEMA_DIALECT, **schema}
        for filename, schema in generated.items()
    }
