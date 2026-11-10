"""Temperature history for one vial."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from evolver.db.models import TemperatureReading


def get_temperature_history(
    session: Session, vial_id: int, limit: int = 100
) -> list[TemperatureReading]:
    if limit < 1:
        raise ValueError("limit must be positive")
    return list(
        session.scalars(
            select(TemperatureReading)
            .where(TemperatureReading.vial_id == vial_id)
            .order_by(TemperatureReading.generated_at.desc())
            .limit(limit)
        )
    )
