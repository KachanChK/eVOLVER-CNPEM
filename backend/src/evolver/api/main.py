"""HTTP API for the local experiment interface."""

import json
import os
from collections.abc import Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from evolver.db.models import (
    OD_MAX,
    OD_MIN,
    Experiment,
    OdReading,
    PhReading,
    PumpControl,
    TemperatureReading,
    Vial,
)
from evolver.db.queries import get_temperature_history
from evolver.ingestion.control import pause_control, queue_command, resume_control
from evolver_contracts.pilot import EQUIPMENT_ID, VialID
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    WithJsonSchema,
    field_validator,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    app.state.sessions = sessionmaker(engine, expire_on_commit=False)
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(title="eVOLVER CNPEM", lifespan=lifespan)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


Database = Annotated[Session, Depends(get_session)]
ExperimentID = Annotated[int, Path(gt=0, le=2**63 - 1)]
OdLimit = Annotated[
    Decimal,
    Field(strict=True, allow_inf_nan=False, ge=OD_MIN, le=OD_MAX),
    WithJsonSchema({"type": "number", "minimum": 0.10, "maximum": 0.80}, mode="validation"),
]
# PostgreSQL's unconstrained NUMERIC supports up to 16,383 fractional digits.
OD_MAX_SCALE = 16_383


def decode_decimal(token: str) -> Decimal:
    try:
        return Decimal(token)
    except InvalidOperation:
        # A JSON exponent beyond Decimal's representable range is invalid for OD.
        return Decimal("NaN")


class DecimalRequest(Request):
    async def json(self) -> object:
        if not hasattr(self, "_json"):
            self._json = json.loads(
                await self.body(), parse_float=decode_decimal, parse_constant=decode_decimal
            )
        return self._json


class DecimalRequestRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            return await handler(DecimalRequest(request.scope, request.receive))

        return handle


experiment_creation = APIRouter(route_class=DecimalRequestRoute)


class CreateExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    culture_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    vial_id: VialID
    od_min: OdLimit
    od_max: OdLimit

    @field_validator("od_min", "od_max", mode="before")
    @classmethod
    def accept_json_integers(cls, value: object) -> object:
        return Decimal(value) if type(value) is int else value

    @field_validator("od_min", "od_max")
    @classmethod
    def require_storable_scale(cls, value: Decimal) -> Decimal:
        sign, digits, exponent = value.as_tuple()
        if exponent < -OD_MAX_SCALE:
            excess = -exponent - OD_MAX_SCALE
            if any(digits[-excess:]):
                raise ValueError("O limite de OD aceita até 16383 casas decimais significativas.")
            return Decimal((sign, digits[:-excess], -OD_MAX_SCALE))
        return value

    @field_validator("od_max")
    @classmethod
    def require_ordered_od_limits(cls, value: Decimal, info: ValidationInfo) -> Decimal:
        minimum = info.data.get("od_min")
        if minimum is not None and value <= minimum:
            raise ValueError("A OD máxima deve ser maior que a OD mínima.")
        return value

    @field_validator("culture_type")
    @classmethod
    def reject_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Tipo de cultura não pode conter o caractere NUL (U+0000).")
        return value


class ExperimentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    culture_type: str | None
    od_min: Decimal | None
    od_max: Decimal | None
    vial_id: int
    status: str
    started_at: datetime
    ended_at: datetime | None


class VialView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vial_id: int
    label: str | None


class PumpView(BaseModel):
    state: Literal[
        "automatic", "pausing", "paused", "off_unconfirmed", "resuming", "resume_off_unconfirmed"
    ]
    ending: bool


class ReadingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    temperature_celsius: float
    generated_at: datetime
    received_at: datetime


class OtherReadingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    value: float
    generated_at: datetime
    received_at: datetime


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Keep Decimal values in validation errors serializable, including NaN and infinity.
    detail = jsonable_encoder(exc.errors(), custom_encoder={Decimal: str})
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Banco de dados indisponível."})


def visible_experiment(db: Session, experiment_id: int, *, lock: bool = False) -> Experiment:
    query = select(Experiment).where(
        Experiment.id == experiment_id, Experiment.deleted_at.is_(None)
    )
    experiment = db.scalar(query.with_for_update() if lock else query)
    if experiment is None:
        raise HTTPException(404, "Experimento não encontrado.")
    return experiment


@app.get("/api/vials/available", response_model=list[VialView])
def available_vials(db: Database) -> list[Vial]:
    occupied = select(Experiment.vial_id).where(Experiment.ended_at.is_(None))
    return list(
        db.scalars(
            select(Vial)
            .where(Vial.equipment_id == EQUIPMENT_ID, Vial.vial_id.not_in(occupied))
            .order_by(Vial.vial_id)
        )
    )


@app.get("/api/experiments", response_model=list[ExperimentView])
def list_experiments(db: Database) -> list[Experiment]:
    return list(
        db.scalars(
            select(Experiment)
            .where(Experiment.deleted_at.is_(None))
            .order_by(Experiment.started_at.desc(), Experiment.id.desc())
        )
    )


@experiment_creation.post("/api/experiments", status_code=201, response_model=ExperimentView)
def create_experiment(data: CreateExperiment, db: Database) -> Experiment:
    vial = db.get(Vial, data.vial_id, with_for_update=True)
    if vial is None or vial.equipment_id != EQUIPMENT_ID:
        raise HTTPException(404, "Vial não encontrado.")
    if (
        db.scalar(
            select(Experiment.id).where(
                Experiment.vial_id == vial.vial_id, Experiment.ended_at.is_(None)
            )
        )
        is not None
    ):
        raise HTTPException(409, "Este vial já está em uso. Escolha outro vial.")
    experiment = Experiment(
        name=data.name,
        culture_type=data.culture_type,
        od_min=data.od_min,
        od_max=data.od_max,
        vial_id=data.vial_id,
        started_at=func.clock_timestamp(),
    )
    db.add(experiment)
    try:
        db.flush()
        db.add(PumpControl(
            experiment_id=experiment.id, vial_id=experiment.vial_id,
            paused=False, ending=False, delete_requested=False,
            confirmed_state="off", desired_state="off",
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != (
            "uq_experiments_active_vial"
        ):
            raise
        raise HTTPException(409, "Este vial já está em uso. Escolha outro vial.") from exc
    db.refresh(experiment)
    return experiment


app.include_router(experiment_creation)


def pump_view(control: PumpControl) -> PumpView:
    if control.resume_pending:
        state = "resuming" if control.pending_command_id is not None else "resume_off_unconfirmed"
    elif not control.paused:
        state = "automatic"
    elif control.pending_command_id is not None:
        state = "pausing"
    elif control.confirmed_state == "off" and not control.reconcile_required:
        state = "paused"
    else:
        state = "off_unconfirmed"
    return PumpView(state=state, ending=control.ending)


@app.get("/api/experiments/{experiment_id}", response_model=ExperimentView)
def experiment_details(experiment_id: ExperimentID, db: Database) -> Experiment:
    return visible_experiment(db, experiment_id)


@app.get("/api/experiments/{experiment_id}/pump", response_model=PumpView)
def get_pump(experiment_id: ExperimentID, db: Database) -> PumpView:
    visible_experiment(db, experiment_id)
    return pump_view(db.get(PumpControl, experiment_id))


@app.post("/api/experiments/{experiment_id}/pump/pause", response_model=PumpView)
def pause_pump(experiment_id: ExperimentID, db: Database) -> PumpView:
    return change_pump_mode(db, experiment_id, pause_control)


@app.post("/api/experiments/{experiment_id}/pump/resume", response_model=PumpView)
def resume_pump(experiment_id: ExperimentID, db: Database) -> PumpView:
    return change_pump_mode(db, experiment_id, resume_control)


def change_pump_mode(
    db: Session, experiment_id: int, change: Callable[[Connection, int, datetime], None],
) -> PumpView:
    experiment = visible_experiment(db, experiment_id, lock=True)
    control = db.get(PumpControl, experiment_id, with_for_update=True)
    if experiment.ended_at is not None or control.ending:
        raise HTTPException(409, "A bomba só pode ser controlada em um experimento ativo.")
    change(db.connection(), experiment_id, db.scalar(select(func.clock_timestamp())))
    db.refresh(control)
    result = pump_view(control)
    db.commit()
    return result


@app.get("/api/experiments/{experiment_id}/temperature-readings", response_model=list[ReadingView])
def temperature_history(experiment_id: ExperimentID, db: Database) -> list[TemperatureReading]:
    visible_experiment(db, experiment_id)
    return get_temperature_history(db, experiment_id)


@app.get(
    "/api/experiments/{experiment_id}/readings/{measurement_type}",
    response_model=list[OtherReadingView],
)
def other_history(
    experiment_id: ExperimentID, measurement_type: Literal["ph", "od"], db: Database
) -> list[PhReading] | list[OdReading]:
    visible_experiment(db, experiment_id)
    model = PhReading if measurement_type == "ph" else OdReading
    return list(
        db.scalars(
            select(model)
            .where(model.experiment_id == experiment_id)
            .order_by(model.generated_at, model.event_id)
        )
    )


@app.post("/api/experiments/{experiment_id}/inactivate", response_model=ExperimentView)
def inactivate_experiment(experiment_id: ExperimentID, db: Database) -> Experiment:
    experiment = visible_experiment(db, experiment_id, lock=True)
    if experiment.ended_at is None:
        request_end(db, experiment, delete=False)
    db.commit()
    return experiment


@app.delete("/api/experiments/{experiment_id}", status_code=204)
def delete_experiment(experiment_id: ExperimentID, db: Database) -> Response:
    experiment = visible_experiment(db, experiment_id, lock=True)
    if experiment.ended_at is None:
        request_end(db, experiment, delete=True)
    else:
        experiment.deleted_at = db.scalar(select(func.clock_timestamp()))
    db.commit()
    return Response(status_code=204)


def request_end(db: Session, experiment: Experiment, *, delete: bool) -> None:
    control = db.get(PumpControl, experiment.id, with_for_update=True)
    now = db.scalar(select(func.clock_timestamp()))
    control.paused = True
    control.resume_pending = False
    control.ending = True
    control.delete_requested = control.delete_requested or delete
    if control.confirmed_state == "off" and control.pending_command_id is None:
        experiment.ended_at = now
        if control.delete_requested:
            experiment.deleted_at = now
    elif control.pending_command_id is None:
        db.flush()
        queue_command(db.connection(), experiment.id, experiment.vial_id,
                      "turn_off", None, now, "ending")
