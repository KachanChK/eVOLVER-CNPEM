"""Messages for active vial allocation queries."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EQUIPMENT_ID = "evolver-sim-01"
TOPIC_PREFIX = f"evolver/v1/{EQUIPMENT_ID}"
ACTIVE_VIALS_REQUEST = f"{TOPIC_PREFIX}/active-vials/request"
ACTIVE_VIALS_RESPONSE = f"{TOPIC_PREFIX}/active-vials/response"
TELEMETRY_MODE_PROPERTY = "evolver-telemetry-mode"
DatabaseID = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]
VialID = Annotated[int, Field(strict=True, ge=1, le=12)]


class AllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    include_test_state: bool = False


class PumpTestState(BaseModel):
    automatic: bool
    confirmed_state: Literal["on", "off", "unknown"]
    od_min: Decimal | None
    od_max: Decimal | None
    pending: bool


class ActiveVial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vial_id: VialID
    experiment_id: DatabaseID
    allocation_id: UUID | None = None
    experiment_name: str | None = None
    pump_test: PumpTestState | None = None


class AllocationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    vials: list[ActiveVial] = Field(max_length=12)
    od_alert_range: tuple[float, float] | None = None
