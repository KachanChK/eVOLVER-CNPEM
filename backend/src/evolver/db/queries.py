"""Temperature history for one experiment."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from evolver.db.models import TemperatureReading


def get_temperature_history(session: Session, experiment_id: int) -> list[TemperatureReading]:
    return list(
        session.scalars(
            select(TemperatureReading)
            .where(TemperatureReading.experiment_id == experiment_id)
            .order_by(TemperatureReading.generated_at, TemperatureReading.event_id)
        )
    )
