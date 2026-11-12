"""Messages for the local temperature pilot."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat

EQUIPMENT_ID = "evolver-sim-01"
TOPIC_PREFIX = f"evolver/dev/{EQUIPMENT_ID}"
TELEMETRY_TOPIC = f"{TOPIC_PREFIX}/telemetry"
ACTIVE_VIALS_REQUEST = f"{TOPIC_PREFIX}/active-vials/request"
ACTIVE_VIALS_RESPONSE = f"{TOPIC_PREFIX}/active-vials/response"
DatabaseID = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]
VialID = Annotated[int, Field(strict=True, ge=1, le=12)]


class AllocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID


class ActiveVial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vial_id: VialID
    experiment_id: DatabaseID


class AllocationResponse(AllocationRequest):
    vials: list[ActiveVial] = Field(max_length=12)


class TemperatureMessage(ActiveVial):
    equipment_id: str
    event_id: UUID
    measurement: Literal["temperature"]
    value: FiniteFloat
    unit: Literal["celsius"]
    generated_at: AwareDatetime
