"""HTTP API for the local experiment interface."""

import os
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from evolver.db.models import Experiment, OdReading, PhReading, TemperatureReading, Vial
from evolver.db.queries import get_temperature_history
from evolver_contracts.pilot import EQUIPMENT_ID, VialID
from fastapi import Depends, FastAPI, HTTPException, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import create_engine, func, select
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


class CreateExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    vial_id: VialID


class ExperimentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    vial_id: int
    status: str
    started_at: datetime
    ended_at: datetime | None


class VialView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vial_id: int
    label: str | None


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


@app.post("/api/experiments", status_code=201, response_model=ExperimentView)
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
    experiment = Experiment(name=data.name, vial_id=data.vial_id, started_at=func.clock_timestamp())
    db.add(experiment)
    try:
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


@app.get("/api/experiments/{experiment_id}", response_model=ExperimentView)
def experiment_details(experiment_id: ExperimentID, db: Database) -> Experiment:
    return visible_experiment(db, experiment_id)


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
        experiment.ended_at = db.scalar(select(func.clock_timestamp()))
    db.commit()
    return experiment


@app.delete("/api/experiments/{experiment_id}", status_code=204)
def delete_experiment(experiment_id: ExperimentID, db: Database) -> Response:
    experiment = visible_experiment(db, experiment_id, lock=True)
    deleted_at = db.scalar(select(func.clock_timestamp()))
    experiment.ended_at = experiment.ended_at or deleted_at
    experiment.deleted_at = deleted_at
    db.commit()
    return Response(status_code=204)
