"""Persisted OD hysteresis controller for the simulated pump."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from evolver.db.models import OD_MAX, OD_MIN
from evolver_contracts.models import PumpCommand
from evolver_contracts.pilot import EQUIPMENT_ID
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .alerts import emit_alert, resolve_alert

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
                   c.paused, c.ending, c.confirmed_state, c.last_generated_at,
                   c.last_producer_id, c.last_sequence,
                   c.pending_command_id, c.reconcile_required, c.resume_pending,
                   EXISTS (
                       SELECT 1 FROM alerts a WHERE a.allocation_id = e.allocation_id
                         AND a.type = 'pump' AND a.resolved_at IS NULL
                   ) AS recovering
            FROM experiments e JOIN pump_control c ON c.experiment_id = e.id
            WHERE e.id = :experiment_id FOR UPDATE OF e, c
        """),
        {"experiment_id": reading["experiment_id"]},
    ).mappings().one_or_none()
    if row is None or row.ended_at is not None or row.ending:
        return
    value = Decimal(str(reading["value"]))
    if not value.is_finite() or not OD_MIN <= value <= OD_MAX:
        return
    if row.last_generated_at is not None and (
        reading["generated_at"] < row.last_generated_at
        or (reading["generated_at"] == row.last_generated_at and (
            reading["producer_id"] != row.last_producer_id
            or reading["sequence"] <= row.last_sequence
        ))
    ):
        return
    restarted = row.last_generated_at is not None and (
        reading["producer_id"] != row.last_producer_id
        or reading["sequence"] <= row.last_sequence
    )
    if restarted:
        connection.execute(text("""
            UPDATE pump_control SET confirmed_state = 'unknown', reconcile_required = true
            WHERE experiment_id = :experiment_id
        """), reading)
    connection.execute(
        text("""
            UPDATE pump_control SET last_generated_at = :generated_at,
                last_producer_id = :producer_id,
                last_sequence = :sequence, last_event_id = :event_id
            WHERE experiment_id = :experiment_id
        """),
        reading,
    )
    if not is_fresh_od(reading["generated_at"], now) or row.pending_command_id is not None:
        return
    if row.recovering:
        return
    if restarted or (row.reconcile_required and not row.paused):
        connection.execute(text("""
            UPDATE pump_control SET reconcile_required = false
            WHERE experiment_id = :experiment_id
        """), reading)
        reason = "resume_reconcile" if row.resume_pending else "reconcile"
        queue_command(connection, row.id, row.vial_id, "turn_off", reading, now, reason)
        return
    if (
        row.paused or row.resume_pending or row.confirmed_state not in ("on", "off")
        or row.od_min is None or row.od_max is None
        or not row.od_min < row.od_max
    ):
        return
    action = action_for_od(row.confirmed_state, value, row.od_min, row.od_max)
    if action:
        queue_command(
            connection, row.id, row.vial_id, action, reading, now,
            "od_max" if action == "turn_on" else "od_min",
        )


def invalidate_controls(connection: Connection) -> None:
    """Require a fresh safe-off result after the ingestion MQTT session changes."""
    connection.execute(text("""
        WITH active AS MATERIALIZED (
            SELECT id FROM experiments WHERE ended_at IS NULL ORDER BY id FOR UPDATE
        )
        UPDATE pump_control SET confirmed_state = 'unknown', reconcile_required = true
        WHERE experiment_id IN (SELECT id FROM active)
    """))


def queue_safety_offs(connection: Connection, now: datetime) -> None:
    """Recover paused or ending experiments when the MQTT session returns."""
    rows = connection.execute(text("""
        SELECT e.id, e.vial_id, c.resume_pending FROM experiments e
        JOIN pump_control c ON c.experiment_id = e.id
        WHERE e.ended_at IS NULL AND (c.paused OR c.ending OR c.resume_pending)
          AND c.pending_command_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM alerts a WHERE a.allocation_id = e.allocation_id
                AND a.type = 'pump' AND a.resolved_at IS NULL
          )
        ORDER BY e.id
        FOR UPDATE OF e, c
    """)).mappings().all()
    for row in rows:
        reason = "resume_reconcile" if row.resume_pending else "reconcile"
        queue_command(connection, row.id, row.vial_id, "turn_off", None, now, reason)


def pump_alert_open(connection: Connection, experiment_id: int) -> bool:
    return connection.scalar(text("""
        SELECT EXISTS (
            SELECT 1 FROM alerts a JOIN experiments e USING (allocation_id)
            WHERE e.id = :id AND a.type = 'pump' AND a.resolved_at IS NULL
        )
    """), {"id": experiment_id})


def queue_alert_recoveries(connection: Connection, now: datetime) -> None:
    rows = connection.execute(text("""
        SELECT e.id, e.vial_id, c.resume_pending FROM experiments e
        JOIN pump_control c ON c.experiment_id = e.id
        WHERE e.ended_at IS NULL AND c.pending_command_id IS NULL
          AND EXISTS (
              SELECT 1 FROM alerts a WHERE a.allocation_id = e.allocation_id
                AND a.type = 'pump' AND a.resolved_at IS NULL
          )
        ORDER BY e.id FOR UPDATE OF e, c
    """)).mappings().all()
    for row in rows:
        latest = connection.scalar(text("""
            SELECT max(created_at) FROM pump_commands WHERE experiment_id = :id
        """), {"id": row.id})
        if (latest is None or now - latest >= COMMAND_FOR) and pump_alert_open(connection, row.id):
            reason = "resume_reconcile" if row.resume_pending else "reconcile"
            queue_command(connection, row.id, row.vial_id, "turn_off", None, now, reason)


def report_pump_alert(connection: Connection, row, command_id, status: str, reason: str) -> None:
    emit_alert(connection, row.experiment_id, "pump", {
        "command_id": str(command_id),
        "action": "turn_on" if row.desired_state == "on" else "turn_off",
        "status": status,
        "reason_code": reason,
    })


def queue_command(
    connection: Connection, experiment_id: int, vial_id: int, action: str,
    reading: dict | None, now: datetime, reason: str,
) -> None:
    command_id = uuid4()
    # The experiment lock serializes issuance even when the clock repeats or moves backward.
    last_created_at = connection.scalar(text("""
        SELECT created_at FROM pump_commands WHERE experiment_id = :id
        ORDER BY created_at DESC LIMIT 1
    """), {"id": experiment_id})
    created_at = max(now, last_created_at + timedelta(microseconds=1)) if last_created_at else now
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
            "created_at": created_at, "expires_at": created_at + COMMAND_FOR,
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


def lock_control(connection: Connection, experiment_id: int):
    return connection.execute(text("""
        SELECT e.started_at, e.ended_at, e.od_max, c.*
        FROM experiments e JOIN pump_control c ON c.experiment_id = e.id
        WHERE e.id = :id FOR UPDATE OF e, c
    """), {"id": experiment_id}).mappings().one()


def pause_control(connection: Connection, experiment_id: int, now: datetime) -> None:
    row = lock_control(connection, experiment_id)
    if row.ended_at is not None or row.paused:
        return
    connection.execute(text("""
        UPDATE pump_control SET paused = true, resume_pending = false WHERE experiment_id = :id
    """), {"id": experiment_id})
    needs_off = row.confirmed_state != "off" or row.reconcile_required
    if row.pending_command_id is not None:
        if row.desired_state == "off":
            return
        # A reserved publication may have reached the simulator, even without a PUBACK.
        sent_at = connection.execute(text("""
            UPDATE pump_commands SET result_status = 'superseded', result_at = :now
            WHERE command_id = :id RETURNING sent_at
        """), {"id": row.pending_command_id, "now": now}).one().sent_at
        needs_off = needs_off or sent_at is not None
        connection.execute(text("""
            UPDATE pump_control SET pending_command_id = NULL, desired_state = 'off',
                confirmed_state = CASE WHEN :needs_off THEN 'unknown' ELSE confirmed_state END
            WHERE experiment_id = :id
        """), {"id": experiment_id, "needs_off": needs_off})
    if needs_off:
        queue_command(connection, experiment_id, row.vial_id, "turn_off", None, now, "pause")


def resume_control(connection: Connection, experiment_id: int, now: datetime) -> None:
    row = lock_control(connection, experiment_id)
    if row.ended_at is not None or row.ending or not row.paused:
        return
    needs_off = (
        row.confirmed_state != "off" or row.reconcile_required
        or row.pending_command_id is not None
    )
    connection.execute(text("""
        UPDATE pump_control SET paused = false, resume_pending = :needs_off,
            reconcile_required = :needs_off
        WHERE experiment_id = :id
    """), {"id": experiment_id, "needs_off": needs_off})
    if needs_off:
        if row.pending_command_id is None:
            queue_command(connection, experiment_id, row.vial_id,
                          "turn_off", None, now, "resume_reconcile")
    else:
        queue_resume_on(connection, row, now)


def resume_reading(connection: Connection, row, now: datetime):
    if row.od_max is None or row.last_event_id is None:
        return None
    if not is_fresh_od(row.last_generated_at, now):
        return None
    reading = connection.execute(text("""
        SELECT od.event_id, od.generated_at, od.od_value AS value
        FROM od_readings od
        WHERE od.experiment_id = :id AND od.vial_id = :vial_id
          AND od.generated_at >= :started_at AND od.generated_at = :generated_at
          AND od.event_id = :event_id AND od.allocation_verified AND od.control_eligible
          AND NOT EXISTS (
            SELECT 1 FROM od_readings newer
            WHERE newer.experiment_id = od.experiment_id AND newer.vial_id = od.vial_id
              AND newer.allocation_verified AND newer.control_eligible
              AND newer.generated_at BETWEEN od.generated_at AND :now
              AND (newer.generated_at > od.generated_at OR
                   (newer.producer_id = od.producer_id AND newer.sequence > od.sequence))
          )
    """), {"id": row.experiment_id, "vial_id": row.vial_id, "started_at": row.started_at,
           "generated_at": row.last_generated_at, "event_id": row.last_event_id,
           "now": now}).mappings().one_or_none()
    if reading is None:
        return None
    value = Decimal(str(reading.value))
    if value.is_finite() and OD_MIN <= value <= OD_MAX and value >= row.od_max:
        return reading
    return None


def queue_resume_on(connection: Connection, row, now: datetime) -> None:
    reading = resume_reading(connection, row, now)
    if reading is not None:
        queue_command(connection, row.experiment_id, row.vial_id, "turn_on", reading, now, "resume")


def command_is_current(
    connection: Connection, command: PumpCommand, now: datetime | None = None,
    *, claimed_here: bool = False,
) -> bool:
    try:
        allocation_id = UUID(command.experiment_run_id or "")
    except ValueError:
        return False
    experiment_id = connection.scalar(
        text("SELECT id FROM experiments WHERE allocation_id = :allocation_id"),
        {"allocation_id": allocation_id},
    )
    if experiment_id is None:
        return False
    row = lock_control(connection, experiment_id)
    if row.ended_at is not None or row.pending_command_id != command.command_id:
        return False
    now = now if now is not None else connection.scalar(text("SELECT clock_timestamp()"))
    if command.action == "turn_off":
        return command.expires_at > now
    # Leave a blocked ON for result/expiry so the ending path always queues OFF.
    if row.ending:
        return False
    allowed = command.expires_at > now and not (
        row.reconcile_required or row.paused or row.resume_pending
    )
    reason = connection.scalar(text("""
        SELECT reason FROM pump_commands WHERE command_id = :id
    """), {"id": command.command_id})
    if reason != "resume":
        return allowed
    reading = resume_reading(connection, row, now) if allowed else None
    if reading is not None:
        if claimed_here:
            connection.execute(text("""
                UPDATE pump_commands SET reading_event_id = :event,
                    reading_generated_at = :generated_at WHERE command_id = :id
            """), {"id": command.command_id, "event": reading.event_id,
                   "generated_at": reading.generated_at})
        return True
    # Only the owner of this fresh claim can prove that publish() has not been called.
    cancelled = connection.execute(text("""
        UPDATE pump_commands SET result_status = 'superseded', result_at = :now, sent_at = NULL
        WHERE command_id = :id AND result_status = 'pending'
          AND (sent_at IS NULL OR :claimed_here)
    """), {"id": command.command_id, "now": now, "claimed_here": claimed_here}).rowcount
    if cancelled:
        connection.execute(text("""
            UPDATE pump_control SET pending_command_id = NULL, desired_state = 'off'
            WHERE experiment_id = :id
        """), {"id": row.experiment_id})
    return False


def pending_commands(connection: Connection, now: datetime) -> list[PumpCommand]:
    rows = connection.execute(
        text("""
            SELECT p.command_id, e.allocation_id, p.desired_state, p.created_at, p.expires_at
            FROM pump_commands p JOIN pump_control c
              ON c.pending_command_id = p.command_id
            JOIN experiments e ON e.id = p.experiment_id
            WHERE p.sent_at IS NULL AND p.result_status = 'pending'
              AND (p.desired_state = 'off' OR
                   (NOT c.reconcile_required AND NOT c.paused AND NOT c.ending
                    AND NOT c.resume_pending))
              AND p.expires_at > :now ORDER BY p.created_at
        """),
        {"now": now},
    ).mappings().all()
    return [PumpCommand(
        schema_version="1.0", command_id=row.command_id,
        equipment_id=EQUIPMENT_ID, experiment_run_id=str(row.allocation_id),
        author_id=AUTHOR_ID, created_at=row.created_at, expires_at=row.expires_at,
        target_type="pump", pump_id=1,
        action="turn_on" if row.desired_state == "on" else "turn_off",
    ) for row in rows]


def expire_commands(
    connection: Connection, now: datetime, *, experiment_id: int | None = None,
) -> None:
    rows = connection.execute(
        text("""
            WITH affected AS MATERIALIZED (
                SELECT e.id FROM experiments e
                WHERE (CAST(:id AS bigint) IS NULL OR e.id = :id) AND EXISTS (
                    SELECT 1 FROM pump_commands p WHERE p.experiment_id = e.id
                      AND p.result_status IN ('pending', 'received') AND p.expires_at <= :now
                ) ORDER BY e.id FOR UPDATE
            )
            UPDATE pump_commands SET result_status = CASE
                WHEN reason = 'resume' AND sent_at IS NULL
                  AND puback_at IS NULL AND received_at IS NULL THEN 'superseded'
                ELSE 'unknown' END, result_at = :now
            WHERE result_status IN ('pending', 'received')
              AND expires_at <= :now
              AND experiment_id IN (SELECT id FROM affected)
            RETURNING command_id, experiment_id, desired_state, reason, result_status,
                      puback_at IS NOT NULL OR received_at IS NOT NULL AS dispatched
        """), {"now": now, "id": experiment_id},
    ).mappings().all()
    for row in rows:
        if row.result_status == "unknown" and row.dispatched:
            report_pump_alert(connection, row, row.command_id, "unconfirmed", "timeout")
        recovering = pump_alert_open(connection, row.experiment_id)
        cleared = connection.execute(text("""
            UPDATE pump_control SET pending_command_id = NULL,
                confirmed_state = CASE WHEN :result_status = 'unknown' THEN 'unknown'
                    ELSE confirmed_state END,
                desired_state = CASE WHEN :result_status = 'superseded' THEN 'off'
                    ELSE desired_state END,
                reconcile_required = reconcile_required OR :recovering OR resume_pending OR
                    (:reason = 'resume' AND :result_status = 'unknown')
            WHERE experiment_id = :experiment_id AND pending_command_id = :command_id
        """), dict(row, recovering=recovering))
        if cleared.rowcount:
            control = connection.execute(text("""
                SELECT vial_id, ending, paused, reconcile_required, resume_pending FROM pump_control
                WHERE experiment_id = :experiment_id FOR UPDATE
            """), row).mappings().one()
            if recovering and not control.ending:
                continue
            if control.resume_pending and row.desired_state == "off":
                if row.reason != "resume_reconcile":
                    queue_command(connection, row.experiment_id, control.vial_id,
                                  "turn_off", None, now, "resume_reconcile")
            elif (control.ending or control.paused) and (
                row.desired_state == "on"
                or (control.ending and control.reconcile_required
                    and row.reason not in ("ending", "reconcile"))
            ):
                queue_command(connection, row.experiment_id, control.vial_id,
                              "turn_off", None, now,
                              "reconcile" if control.reconcile_required else
                              ("ending" if control.ending else "pause"))


def record_result(connection: Connection, result) -> None:
    row = connection.execute(
        text("""
            SELECT p.experiment_id FROM pump_commands p
            JOIN experiments e ON e.id = p.experiment_id
            WHERE p.command_id = :command_id FOR UPDATE OF e
        """), {"command_id": result.command_id},
    ).mappings().one_or_none()
    if row is None:
        return
    control = lock_control(connection, row.experiment_id)
    row = connection.execute(text("""
        SELECT experiment_id, desired_state, result_status, reason, created_at FROM pump_commands
        WHERE command_id = :command_id
    """), {"command_id": result.command_id}).mappings().one()
    reason = getattr(result, "reason_code", None)
    failure = result.status == "failed" or (result.status == "rejected" and reason == "expired")
    late_failure = (
        row.result_status == "unknown" and failure and control.ended_at is None
        and not connection.scalar(text("""
            SELECT EXISTS (
                SELECT 1 FROM pump_commands WHERE experiment_id = :id AND created_at > :created
                  AND desired_state = 'off' AND result_status = 'executed'
            )
        """), {"id": row.experiment_id, "created": row.created_at})
    )
    if row.result_status not in ("pending", "received") and not late_failure:
        return
    connection.execute(text("""
        UPDATE pump_commands SET result_status = :status, result_at = :at,
            received_at = coalesce(received_at, :received_at),
            result_detail = :detail WHERE command_id = :command_id
    """), {"status": result.status, "at": result.reported_at,
           "received_at": result.reported_at if result.status == "received" else None,
           "detail": result.detail, "command_id": result.command_id})
    if failure:
        status = "failed" if result.status == "failed" else "unconfirmed"
        report_pump_alert(connection, row, result.command_id, status, reason)
    if result.status != "received":
        recovering = pump_alert_open(connection, row.experiment_id)
        updated = connection.execute(text("""
            UPDATE pump_control SET
                confirmed_state = CASE WHEN :status = 'executed'
                    AND :desired_state = 'off' THEN 'off'
                    WHEN reconcile_required THEN 'unknown'
                    WHEN :status = 'executed'
                    THEN :desired_state ELSE 'unknown' END,
                reconcile_required = CASE WHEN :status = 'executed'
                    AND :desired_state = 'off' THEN false
                    ELSE reconcile_required OR :recovering OR resume_pending
                        OR (:reason = 'resume' AND :status <> 'executed') END,
                pending_command_id = NULL
            WHERE experiment_id = :experiment_id AND pending_command_id = :command_id
        """), {"status": result.status, "desired_state": row.desired_state, "reason": row.reason,
               "experiment_id": row.experiment_id, "command_id": result.command_id,
               "recovering": recovering})
        if not updated.rowcount:
            return
        control = lock_control(connection, row.experiment_id)
        if row.desired_state == "off" and result.status == "executed":
            now = connection.scalar(text("SELECT clock_timestamp()"))
            resolve_alert(connection, row.experiment_id, "pump", now)
            if control.ending:
                connection.execute(text("""
                    WITH closure AS (SELECT clock_timestamp() AS at)
                    UPDATE experiments SET ended_at = greatest(started_at, closure.at),
                        deleted_at = CASE WHEN :delete THEN greatest(started_at, closure.at) END
                    FROM closure WHERE id = :id
                """), {"id": row.experiment_id, "delete": control.delete_requested})
            elif control.resume_pending and not control.paused:
                connection.execute(text("""
                    UPDATE pump_control SET resume_pending = false WHERE experiment_id = :id
                """), {"id": row.experiment_id})
                queue_resume_on(connection, control, now)
        elif not recovering and row.desired_state == "off" and control.resume_pending:
            if row.reason != "resume_reconcile":
                now = connection.scalar(text("SELECT clock_timestamp()"))
                queue_command(connection, row.experiment_id, control.vial_id,
                              "turn_off", None, now, "resume_reconcile")
        elif row.desired_state == "on" and (control.ending or (not recovering and control.paused)):
            queue_command(connection, row.experiment_id, control.vial_id,
                          "turn_off", None, datetime.now(UTC),
                          "ending" if control.ending else "pause")
