"""Alert transactions and API on a disposable PostgreSQL + TimescaleDB."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from evolver.api.main import app
from evolver.ingestion import telemetry
from evolver.ingestion.alerts import alert_ranges, check_missing_data, emit_alert
from evolver.ingestion.control import (
    expire_commands,
    pending_commands,
    queue_alert_recoveries,
    queue_command,
    record_result,
)
from evolver_contracts.models import (
    ExecutedCommandResult,
    FailedCommandResult,
    ReceivedCommandResult,
    RejectedCommandResult,
    TelemetryEvent,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.integration
TOPIC = "evolver/v1/evolver-sim-01/telemetry"


@pytest.fixture
def stack(monkeypatch):
    url = os.getenv("EVOLVER_ALERT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set EVOLVER_ALERT_TEST_DATABASE_URL to a disposable TimescaleDB database")
    assert make_url(url).database.startswith("evolver_test_")
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        with engine.begin() as db:
            db.execute(text("TRUNCATE experiments, telemetry_events RESTART IDENTITY CASCADE"))
        with TestClient(app) as api:
            yield engine, api, config
    finally:
        engine.dispose()


def allocation(engine, vial=1):
    with engine.begin() as db:
        return db.execute(text("""
            INSERT INTO experiments (vial_id, name, started_at, od_min, od_max)
            VALUES (:vial, 'Ensaio de alerta', clock_timestamp() - interval '1 minute', .2, .7)
            RETURNING id, allocation_id, vial_id
        """), {"vial": vial}).one()


def reading(run, metric, value, when, *, identifier=None, sequence=1):
    return TelemetryEvent(
        schema_version="1.0", event_id=uuid4(), equipment_id="evolver-sim-01",
        producer_id="alert-test", vial_id=str(run.vial_id), measurement_type=metric,
        generated_at=when, sequence=sequence, value=value,
        experiment_run_id=identifier or str(run.allocation_id),
    ).model_dump_json().encode()


def get_alerts(api, **params):
    response = api.get("/api/alerts", params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("metric,low,high", [
    ("temperature", 36.0, 39.0), ("ph", 6.80, 7.50), ("od", 0.10, 0.80),
])
def test_ranges_ignore_history_duplicates_and_out_of_order(stack, metric, low, high):
    engine, api, _ = stack
    run = allocation(engine)
    earlier = datetime.now(UTC) - timedelta(seconds=2)

    def event(value, offset, **kwargs):
        return reading(run, metric, value, earlier + timedelta(milliseconds=offset), **kwargs)

    store = telemetry.store_v1_message
    for value, offset in ((low, 1), (high, 2)):
        assert store(engine, TOPIC, event(value, offset)) == "gravada"
    assert not get_alerts(api)["has_unread"]
    assert store(engine, TOPIC, event(high + 1, 0)) == "gravada"
    assert store(engine, TOPIC, event(high + 1, 3), live=False) == "gravada"
    assert store(engine, TOPIC, event(high + 1, -14_000)) == "gravada"
    assert store(engine, TOPIC, event(high + 1, 4, identifier=str(run.id))) == "gravada"
    assert not get_alerts(api)["items"]
    fault = event(low - 0.01, 5)
    assert store(engine, TOPIC, fault) == "gravada"
    assert store(engine, TOPIC, fault) == "duplicada"
    store(engine, TOPIC, event(high + 1, 6))
    store(engine, TOPIC, event(low, 4))
    first, = get_alerts(api)["items"]
    assert first["allocation_id"] == str(run.allocation_id) and first["type"] == metric
    assert first["resolved_at"] is None and first["details"]["value"] == low - 0.01
    store(engine, TOPIC, event(high, 7))
    store(engine, TOPIC, event(high + 0.01, 8))
    latest, original = get_alerts(api)["items"]
    assert latest["resolved_at"] is None and original["resolved_at"] is not None
    assert latest["details"]["value"] == high + 0.01


def test_upgrade_preserves_prior_data_and_first_check_starts_monitoring(stack):
    engine, api, config = stack
    command.downgrade(config, "20261123_02")
    run = allocation(engine)
    start = datetime.now(UTC)
    with engine.begin() as db:
        db.execute(text("""
            INSERT INTO temperature_readings
                (event_id, generated_at, received_at, vial_id, experiment_id, temperature_celsius)
            VALUES (:event, :at, :at, :vial, :id, 37)
        """), {"event": uuid4(), "at": start, "vial": run.vial_id, "id": run.id})
    command.upgrade(config, "head")
    with engine.begin() as db:
        assert db.scalar(text("SELECT count(*) FROM temperature_readings")) == 1
        assert db.scalar(text("SELECT count(*) FROM alert_monitoring")) == 0
        check_missing_data(db, start)
        check_missing_data(db, start + timedelta(seconds=14, milliseconds=999))
    assert not get_alerts(api)["items"]
    engine.dispose()
    with engine.begin() as db:
        check_missing_data(db, start + timedelta(seconds=15))
    missing, = get_alerts(api)["items"]
    assert missing["details"]["metrics"] == ["temperature", "ph", "od"]


def test_missing_metrics_update_recover_and_do_not_follow_reused_vial(stack):
    engine, api, _ = stack
    run = allocation(engine)
    now = datetime.now(UTC)
    for metric, value, age in (("temperature", 37, 14), ("ph", 7, 5), ("od", .4, 5)):
        telemetry.store_v1_message(
            engine, TOPIC, reading(run, metric, value, now - timedelta(seconds=age)),
        )
    with engine.begin() as db:
        check_missing_data(db, now + timedelta(seconds=1))
    missing, = get_alerts(api)["items"]
    assert missing["details"]["metrics"] == ["temperature"]
    with engine.begin() as db:
        check_missing_data(db, now + timedelta(seconds=10))
    updated, = get_alerts(api, after=missing["id"])["open_missing"]
    assert updated["id"] == missing["id"] and len(updated["details"]["metrics"]) == 3
    for metric, value in (("temperature", 37), ("ph", 7), ("od", .4)):
        telemetry.store_v1_message(
            engine, TOPIC, reading(run, metric, value, now), live=False,
        )
    engine.dispose()
    with engine.begin() as db:
        check_missing_data(db, now + timedelta(seconds=10))
    assert get_alerts(api)["items"][0]["resolved_at"] is None
    for metric, value in (("temperature", 37), ("ph", 7), ("od", .4)):
        telemetry.store_v1_message(engine, TOPIC, reading(run, metric, value, now))
    with engine.begin() as db:
        check_missing_data(db, now + timedelta(seconds=10))
    assert get_alerts(api)["items"][0]["resolved_at"] is not None
    with engine.begin() as db:
        check_missing_data(db, now + timedelta(seconds=15))
        db.execute(text("UPDATE experiments SET ended_at = now() WHERE id = :id"), {"id": run.id})
    replacement = allocation(engine)
    with engine.begin() as db:
        check_missing_data(db, now + timedelta(seconds=16))
    rows = get_alerts(api)["items"]
    assert len(rows) == 2
    assert all(row["resolved_at"] and row["experiment_id"] != replacement.id for row in rows)


def test_telemetry_rows_and_alerts_roll_back_together(stack, monkeypatch):
    engine, api, _ = stack
    run = allocation(engine)
    with engine.connect() as db:
        generated_at = db.scalar(text("SELECT clock_timestamp()"))
    payload = reading(run, "ph", 7.70, generated_at)
    original = telemetry.monitor_reading

    def fail(*args):
        original(*args)
        raise RuntimeError("forced rollback")

    with monkeypatch.context() as context:
        context.setattr(telemetry, "monitor_reading", fail)
        with pytest.raises(RuntimeError, match="forced rollback"):
            telemetry.store_v1_message(engine, TOPIC, payload)
    assert get_alerts(api)["items"] == []
    assert telemetry.store_v1_message(engine, TOPIC, payload) == "gravada"
    assert len(get_alerts(api)["items"]) == 1


def test_concurrent_emission_and_cursor_actions_preserve_newer_alerts(stack):
    engine, api, _ = stack
    run, second = allocation(engine), allocation(engine, 2)
    started = Event()

    def concurrent_ph(experiment):
        with engine.begin() as db:
            started.set()
            emit_alert(db, experiment.id, "ph", {"value": 7.7})

    with ThreadPoolExecutor(max_workers=2) as pool:
        with engine.begin() as db:
            emit_alert(db, run.id, "ph", {"value": 7.7})
            same = pool.submit(concurrent_ph, run)
            other = pool.submit(concurrent_ph, second)
            assert started.wait(2)
            assert get_alerts(api)["items"] == []
        same.result(timeout=3)
        other.result(timeout=3)
        latest, first = get_alerts(api)["items"]
        assert first["id"] < latest["id"]
        with engine.begin() as db:
            emit_alert(db, run.id, "ph", {"value": 7.8})
            emit_alert(db, run.id, "od", {"value": .85})
            pending = pool.submit(api.post, "/api/alerts/clear", json={"cursor": latest["id"]})
        assert pending.result(timeout=3).status_code == 204
    unarchived, = get_alerts(api, after=latest["id"])["new"]
    assert unarchived["type"] == "od"
    for _ in range(2):
        assert api.post("/api/alerts/clear", json={"cursor": latest["id"]}).status_code == 204
        assert api.post("/api/alerts/read", json={"cursor": latest["id"]}).status_code == 204
    assert get_alerts(api)["has_unread"]
    assert api.post("/api/alerts/read", json={"cursor": unarchived["id"]}).status_code == 204
    assert not get_alerts(api)["has_unread"]
    with engine.begin() as db:
        emit_alert(db, run.id, "ph", {"value": 7.7})
        emit_alert(db, second.id, "temperature", {"value": 40})
        db.execute(text("""
            UPDATE alerts SET emitted_at = (SELECT max(emitted_at) FROM alerts)
            WHERE archived_at IS NULL
        """))
        assert db.scalar(text("SELECT count(*) FROM alerts")) == 4
    page = get_alerts(api, limit=1)
    older, = get_alerts(api, before=page["next_before"], limit=1)["items"]
    assert older["id"] == unarchived["id"]


@pytest.mark.parametrize("mode", [
    "failed", "expired", "puback", "received", "reserved", "cancelled", "invalid",
])
def test_pump_alert_evidence_and_safe_off(stack, mode):
    engine, api, _ = stack
    run = allocation(engine)
    created = datetime.now(UTC)
    with engine.begin() as db:
        db.execute(text("""
            INSERT INTO pump_control (experiment_id, vial_id, confirmed_state, desired_state)
            VALUES (:id, :vial, 'off', 'off')
        """), {"id": run.id, "vial": run.vial_id})
        queue_command(db, run.id, run.vial_id, "turn_on", None, created, "od_max")
        original, = pending_commands(db, created)
    fields = {
        "schema_version": "1.0", "command_id": original.command_id,
        "equipment_id": "evolver-sim-01", "simulated": True, "reported_at": created,
    }
    with engine.begin() as db:
        if mode == "failed":
            result = FailedCommandResult(status="failed", reason_code="simulation_error", **fields)
            record_result(db, result)
            record_result(db, result)
        elif mode == "expired":
            record_result(db, RejectedCommandResult(
                status="rejected", reason_code="expired", **fields,
            ))
        elif mode == "cancelled":
            db.execute(text("UPDATE pump_commands SET result_status = 'superseded'"))
            record_result(db, FailedCommandResult(
                status="failed", reason_code="simulation_error", **fields,
            ))
        elif mode == "invalid":
            record_result(db, RejectedCommandResult(
                status="rejected", reason_code="invalid_payload", **fields,
            ))
        else:
            db.execute(text("UPDATE pump_commands SET sent_at = :at"), {"at": created})
            if mode == "puback":
                db.execute(text("UPDATE pump_commands SET puback_at = :at"), {"at": created})
            elif mode == "received":
                record_result(db, ReceivedCommandResult(status="received", **fields))
            expire_commands(db, original.expires_at)
    rows = get_alerts(api)["items"]
    if mode in ("reserved", "cancelled", "invalid"):
        assert rows == []
        return
    alert, = rows
    assert alert["details"]["command_id"] == str(original.command_id)
    assert alert["details"]["status"] == ("failed" if mode == "failed" else "unconfirmed")
    with engine.begin() as db:
        queue_alert_recoveries(db, created + timedelta(seconds=9, milliseconds=999))
        assert not pending_commands(db, created)
        queue_alert_recoveries(db, original.expires_at)
        recovery, = pending_commands(db, original.expires_at)
        queue_alert_recoveries(db, original.expires_at)
        assert pending_commands(db, original.expires_at) == [recovery]
        assert recovery.action == "turn_off" and recovery.command_id != original.command_id
        record_result(db, ExecutedCommandResult(
            status="executed", **dict(fields, command_id=recovery.command_id),
        ))
    resolved, = get_alerts(api)["items"]
    assert resolved["id"] == alert["id"] and resolved["resolved_at"]


@pytest.mark.parametrize("minimum,maximum", [("NaN", "39"), ("36", "inf"), ("39", "39")])
def test_rejects_invalid_alert_ranges(monkeypatch, minimum, maximum):
    monkeypatch.setenv("ALERT_TEMPERATURE_MIN", minimum)
    monkeypatch.setenv("ALERT_TEMPERATURE_MAX", maximum)
    alert_ranges.cache_clear()
    with pytest.raises(ValueError, match="ALERT_TEMPERATURE"):
        alert_ranges()
