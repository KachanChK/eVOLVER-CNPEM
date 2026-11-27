"""Evaluate persistent alert occurrences under the experiment row lock."""

import json
import math
import os
from datetime import datetime, timedelta
from functools import lru_cache

from evolver_contracts.pilot import EQUIPMENT_ID
from sqlalchemy import text
from sqlalchemy.engine import Connection

FRESH_FOR = timedelta(seconds=15)
METRICS = {"temperature": (36.0, 39.0, "°C"), "ph": (6.80, 7.50, None), "od": (0.10, 0.80, None)}


@lru_cache(maxsize=1)
def alert_ranges() -> dict[str, tuple[float, float]]:
    ranges = {}
    for metric, (low, high, _) in METRICS.items():
        prefix = f"ALERT_{metric.upper()}"
        try:
            minimum = float(os.getenv(f"{prefix}_MIN", str(low)))
            maximum = float(os.getenv(f"{prefix}_MAX", str(high)))
            if not (math.isfinite(minimum) and math.isfinite(maximum) and minimum < maximum):
                raise ValueError
        except ValueError as exc:
            raise ValueError(f"{prefix}_MIN/MAX devem ser finitos e crescentes") from exc
        ranges[metric] = minimum, maximum
    return ranges


def lock_alert_writes(connection: Connection) -> None:
    # Hold the emission lock through commit, so an ID cannot become visible out of order.
    connection.execute(text("SELECT pg_advisory_xact_lock(43396, 1)"))


def emit_alert(connection: Connection, experiment_id: int, kind: str, details: dict) -> None:
    params = {"experiment_id": experiment_id, "type": kind, "details": json.dumps(details)}
    if connection.scalar(text("""
        SELECT EXISTS (
            SELECT 1 FROM alerts a JOIN experiments e USING (allocation_id)
            WHERE e.id = :experiment_id AND a.type = :type AND a.resolved_at IS NULL
        )
    """), params):
        return
    lock_alert_writes(connection)
    connection.execute(text("""
        INSERT INTO alerts (allocation_id, experiment_id, experiment_name, vial_id,
                            type, emitted_at, details)
        SELECT e.allocation_id, e.id, e.name, e.vial_id, :type,
               greatest(clock_timestamp(),
                        (SELECT emitted_at FROM alerts ORDER BY id DESC LIMIT 1)),
               CAST(:details AS jsonb)
        FROM experiments e
        WHERE e.id = :experiment_id AND e.ended_at IS NULL
        ON CONFLICT (allocation_id, type) WHERE resolved_at IS NULL DO NOTHING
    """), params)


def resolve_alert(connection: Connection, experiment_id: int, kind: str, now: datetime) -> None:
    connection.execute(text("""
        UPDATE alerts SET resolved_at = greatest(:now, emitted_at)
        WHERE allocation_id = (SELECT allocation_id FROM experiments WHERE id = :experiment_id)
          AND type = :type AND resolved_at IS NULL
    """), {"experiment_id": experiment_id, "type": kind, "now": now})


def monitor_reading(connection: Connection, reading: dict, now: datetime) -> None:
    metric = reading["measurement_type"]
    column = f"{metric}_at"
    minimum, maximum = alert_ranges()[metric]
    in_range = minimum <= reading["value"] <= maximum
    advanced = connection.scalar(text(f"""
        WITH live AS (
            INSERT INTO alert_monitoring (allocation_id, {column})
            SELECT allocation_id, :generated_at
            FROM experiments WHERE id = :experiment_id AND ended_at IS NULL
            ON CONFLICT (allocation_id) DO UPDATE SET {column} = excluded.{column}
            WHERE alert_monitoring.{column} IS NULL OR alert_monitoring.{column} < excluded.{column}
            RETURNING allocation_id
        ), recovered AS (
            UPDATE alerts a SET resolved_at = greatest(:now, emitted_at)
            FROM live WHERE a.allocation_id = live.allocation_id
              AND a.type = :measurement_type AND a.resolved_at IS NULL AND :in_range
        )
        SELECT EXISTS (SELECT 1 FROM live)
    """), dict(reading, now=now, in_range=in_range))
    if advanced and not in_range:
        emit_alert(connection, reading["experiment_id"], metric, {
            "value": reading["value"], "minimum": minimum, "maximum": maximum,
            "unit": METRICS[metric][2], "event_id": str(reading["event_id"]),
            "generated_at": reading["generated_at"].isoformat(),
        })


def check_missing_data(connection: Connection, now: datetime) -> None:
    allocations = connection.execute(text("""
        SELECT e.id, e.allocation_id FROM experiments e JOIN vials v USING (vial_id)
        WHERE e.ended_at IS NULL AND v.equipment_id = :equipment
        ORDER BY e.id FOR UPDATE OF e
    """), {"equipment": EQUIPMENT_ID}).mappings().all()
    lock_alert_writes(connection)
    if allocations:
        params = {"now": now, "ids": [row.allocation_id for row in allocations]}
        connection.execute(text("""
            INSERT INTO alert_monitoring (allocation_id, started_at)
            SELECT unnest(CAST(:ids AS uuid[])), :now
            ON CONFLICT (allocation_id) DO UPDATE SET started_at = excluded.started_at
            WHERE alert_monitoring.started_at IS NULL
        """), params)
        monitoring = connection.execute(text("""
            SELECT e.id, m.*, a.id AS alert_id, a.details
            FROM alert_monitoring m JOIN experiments e USING (allocation_id)
            LEFT JOIN alerts a ON a.allocation_id = m.allocation_id
                AND a.type = 'missing_data' AND a.resolved_at IS NULL
            WHERE m.allocation_id = ANY(:ids) ORDER BY e.id
        """), params).mappings()
        for row in monitoring:
            metrics = [
                metric for metric in METRICS
                if now - (row[f"{metric}_at"] or row.started_at) >= FRESH_FOR
            ]
            if metrics:
                details = {"metrics": metrics}
                if row.alert_id is None:
                    emit_alert(connection, row.id, "missing_data", details)
                elif row.details != details:
                    connection.execute(text("""
                        UPDATE alerts SET details = CAST(:details AS jsonb) WHERE id = :id
                    """), {"id": row.alert_id, "details": json.dumps(details)})
            elif row.alert_id is not None:
                resolve_alert(connection, row.id, "missing_data", now)
    connection.execute(text("""
        UPDATE alerts a SET resolved_at = e.ended_at
        FROM experiments e
        WHERE e.id = a.experiment_id AND e.ended_at IS NOT NULL AND a.resolved_at IS NULL
    """))
