"""Read queries that keep production time separate from arrival time."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

CURRENT_MEASUREMENTS_SQL = text(
    """
    SELECT event_id, generated_at, received_at, equipment_id, position_id,
           experiment_run_id, producer_id, sequence, measurement_type, value, schema_version
    FROM latest_measurements
    WHERE (CAST(:equipment_id AS varchar) IS NULL OR equipment_id = :equipment_id)
      AND (CAST(:position_id AS uuid) IS NULL OR position_id = :position_id)
      AND (CAST(:measurement_type AS varchar) IS NULL OR measurement_type = :measurement_type)
    ORDER BY equipment_id, position_id, measurement_type
    """
)

MEASUREMENT_HISTORY_SQL = text(
    """
    SELECT event_id, generated_at, received_at, equipment_id, position_id,
           experiment_run_id, producer_id, sequence, measurement_type, value, schema_version
    FROM measurements
    WHERE (CAST(:equipment_id AS varchar) IS NULL OR equipment_id = :equipment_id)
      AND (CAST(:position_id AS uuid) IS NULL OR position_id = :position_id)
      AND (CAST(:measurement_type AS varchar) IS NULL OR measurement_type = :measurement_type)
      AND (CAST(:since AS timestamptz) IS NULL OR generated_at >= :since)
      AND (CAST(:until AS timestamptz) IS NULL OR generated_at < :until)
    ORDER BY generated_at ASC, sequence ASC, event_id ASC
    LIMIT :limit
    """
)


def get_current_measurements(
    session: Session,
    *,
    equipment_id: str | None = None,
    position_id: UUID | None = None,
    measurement_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return each selected source/type's latest production measurement."""
    result = session.execute(
        CURRENT_MEASUREMENTS_SQL,
        {
            "equipment_id": equipment_id,
            "position_id": position_id,
            "measurement_type": measurement_type,
        },
    )
    return [dict(row) for row in result.mappings()]


def get_measurement_history(
    session: Session,
    *,
    equipment_id: str | None = None,
    position_id: UUID | None = None,
    measurement_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Read production-time history; late arrivals retain their original time."""
    if limit < 1:
        raise ValueError("limit must be positive")
    result = session.execute(
        MEASUREMENT_HISTORY_SQL,
        {
            "equipment_id": equipment_id,
            "position_id": position_id,
            "measurement_type": measurement_type,
            "since": since,
            "until": until,
            "limit": limit,
        },
    )
    return [dict(row) for row in result.mappings()]
