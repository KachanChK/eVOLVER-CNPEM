"""Persisted OD hysteresis controller for the simulated pump."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from evolver.db.models import OD_MAX, OD_MIN
from evolver_contracts.models import PumpCommand
from evolver_contracts.pilot import EQUIPMENT_ID
from sqlalchemy import text
from sqlalchemy.engine import Connection

FRESH_FOR = timedelta(seconds=10)
COMMAND_FOR = timedelta(seconds=10)
AUTHOR_ID = "evolver-od-control"


def is_fresh_od(generated_at: datetime, now: datetime) -> bool:
    return timedelta(0) <= now - generated_at <= FRESH_FOR


def action_for_od(state: str, value: Decimal, minimum: Decimal, maximum: Decimal) -> str | None:
    if state == "off" and value >= maximum:
        return "turn_on"
    if state == "on" and value <= minimum:
        return "turn_off"
    return None


def consider_od(connection: Connection, reading: dict, now: datetime) -> None:
    """Lock the experiment before comparing the reading and reserving a command."""
    row = connection.execute(
        text("""
            SELECT e.id, e.vial_id, e.od_min, e.od_max, e.ended_at,
                   c.paused, c.confirmed_state, c.last_generated_at,
                   c.last_producer_id, c.last_sequence,
                   c.pending_command_id
            FROM experiments e JOIN pump_control c ON c.experiment_id = e.id
            WHERE e.id = :experiment_id FOR UPDATE OF e, c
        """),
        {"experiment_id": reading["experiment_id"]},
    ).mappings().one_or_none()
    if row is None or row.ended_at is not None:
        return
    value = Decimal(str(reading["value"]))
    if not OD_MIN <= value <= OD_MAX:
        return
    if row.last_generated_at is not None and (
        reading["generated_at"] < row.last_generated_at
        or (reading["generated_at"] == row.last_generated_at and (
            reading["producer_id"] != row.last_producer_id
            or reading["sequence"] <= row.last_sequence
        ))
    ):
        return
    connection.execute(
        text("""
            UPDATE pump_control SET last_generated_at = :generated_at,
                last_producer_id = :producer_id,
                last_sequence = :sequence WHERE experiment_id = :experiment_id
        """),
        reading,
    )
    if (
        row.paused or row.pending_command_id is not None
        or row.confirmed_state not in ("on", "off")
        or row.od_min is None or row.od_max is None
        or not row.od_min < row.od_max
        or not is_fresh_od(reading["generated_at"], now)
    ):
        return
    action = action_for_od(row.confirmed_state, value, row.od_min, row.od_max)
    if action:
        queue_command(
            connection, row.id, row.vial_id, action, reading, now,
            "od_max" if action == "turn_on" else "od_min",
        )


def queue_command(
    connection: Connection, experiment_id: int, vial_id: int, action: str,
    reading: dict | None, now: datetime, reason: str,
) -> None:
    command_id = uuid4()
    connection.execute(
        text("""
            INSERT INTO pump_commands
                (command_id, experiment_id, vial_id, reading_event_id, reading_generated_at,
                 reason, desired_state, created_at, expires_at, result_status)
            VALUES (:command_id, :experiment_id, :vial_id, :reading_event_id,
                    :reading_generated_at, :reason, :desired_state, :created_at,
                    :expires_at, 'pending')
        """),
        {
            "command_id": command_id, "experiment_id": experiment_id, "vial_id": vial_id,
            "reading_event_id": reading["event_id"] if reading else None,
            "reading_generated_at": reading["generated_at"] if reading else None,
            "reason": reason, "desired_state": "on" if action == "turn_on" else "off",
            "created_at": now, "expires_at": now + COMMAND_FOR,
        },
    )
    connection.execute(
        text("""
            UPDATE pump_control SET desired_state = :desired_state,
                pending_command_id = :command_id WHERE experiment_id = :experiment_id
        """),
        {"desired_state": "on" if action == "turn_on" else "off",
         "command_id": command_id, "experiment_id": experiment_id},
    )


def pause_control(connection: Connection, experiment_id: int, now: datetime) -> None:
    row = connection.execute(text("""
        SELECT e.vial_id, e.ended_at, c.confirmed_state, c.pending_command_id
        FROM experiments e JOIN pump_control c ON c.experiment_id = e.id
        WHERE e.id = :id FOR UPDATE OF e, c
    """), {"id": experiment_id}).mappings().one()
    if row.ended_at is not None:
        return
    connection.execute(text("""
        UPDATE pump_control SET paused = true WHERE experiment_id = :id
    """), {"id": experiment_id})
    if row.confirmed_state != "off" and row.pending_command_id is None:
        queue_command(connection, experiment_id, row.vial_id, "turn_off", None, now, "pause")


def pending_commands(connection: Connection, now: datetime) -> list[PumpCommand]:
    rows = connection.execute(
        text("""
            SELECT p.command_id, p.experiment_id, p.desired_state, p.created_at, p.expires_at
            FROM pump_commands p JOIN pump_control c
              ON c.pending_command_id = p.command_id
            WHERE p.sent_at IS NULL AND p.result_status = 'pending'
              AND p.expires_at > :now ORDER BY p.created_at
        """),
        {"now": now},
    ).mappings().all()
    return [PumpCommand(
        schema_version="1.0", command_id=row.command_id,
        equipment_id=EQUIPMENT_ID, experiment_run_id=str(row.experiment_id),
        author_id=AUTHOR_ID, created_at=row.created_at, expires_at=row.expires_at,
        target_type="pump", pump_id=1,
        action="turn_on" if row.desired_state == "on" else "turn_off",
    ) for row in rows]


def expire_commands(connection: Connection, now: datetime) -> None:
    rows = connection.execute(
        text("""
            UPDATE pump_commands SET result_status = 'unknown', result_at = :now
            WHERE result_status IN ('pending', 'received')
              AND expires_at <= :now
            RETURNING command_id, experiment_id, desired_state
        """), {"now": now},
    ).mappings().all()
    for row in rows:
        connection.execute(text("""
            UPDATE pump_control SET confirmed_state = 'unknown', pending_command_id = NULL
            WHERE experiment_id = :experiment_id AND pending_command_id = :command_id
        """), row)
        if row.desired_state == "on":
            control = connection.execute(text("""
                SELECT vial_id, ending, paused FROM pump_control
                WHERE experiment_id = :experiment_id FOR UPDATE
            """), row).mappings().one()
            if control.ending or control.paused:
                queue_command(connection, row.experiment_id, control.vial_id,
                              "turn_off", None, now,
                              "ending" if control.ending else "pause")


def record_result(connection: Connection, result) -> None:
    row = connection.execute(
        text("""
            SELECT p.experiment_id, p.desired_state, p.result_status
            FROM pump_commands p WHERE p.command_id = :command_id FOR UPDATE
        """), {"command_id": result.command_id},
    ).mappings().one_or_none()
    if row is None or row.result_status in ("executed", "rejected", "failed", "unknown"):
        return
    connection.execute(text("""
        UPDATE pump_commands SET result_status = :status, result_at = :at,
            result_detail = :detail WHERE command_id = :command_id
    """), {"status": result.status, "at": result.reported_at,
           "detail": result.detail, "command_id": result.command_id})
    if result.status != "received":
        connection.execute(text("""
            UPDATE pump_control SET
                confirmed_state = CASE WHEN :status = 'executed'
                    THEN :desired_state ELSE 'unknown' END,
                pending_command_id = NULL
            WHERE experiment_id = :experiment_id AND pending_command_id = :command_id
        """), {"status": result.status, "desired_state": row.desired_state,
               "experiment_id": row.experiment_id, "command_id": result.command_id})
        if row.desired_state == "off" and result.status == "executed":
            connection.execute(text("""
                UPDATE experiments e SET ended_at = :at,
                    deleted_at = CASE WHEN c.delete_requested THEN :at ELSE NULL END
                FROM pump_control c WHERE e.id = c.experiment_id
                  AND e.id = :experiment_id AND c.ending
            """), {"at": result.reported_at, "experiment_id": row.experiment_id})
        elif row.desired_state == "on":
            ending = connection.execute(text("""
                SELECT c.vial_id, c.ending, c.paused FROM pump_control c
                WHERE c.experiment_id = :experiment_id FOR UPDATE
            """), {"experiment_id": row.experiment_id}).mappings().one()
            if ending.ending or ending.paused:
                queue_command(connection, row.experiment_id, ending.vial_id,
                              "turn_off", None, datetime.now(UTC),
                              "ending" if ending.ending else "pause")
