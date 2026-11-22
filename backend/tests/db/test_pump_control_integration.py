"""Run against EVOLVER_CONTROL_TEST_DATABASE_URL, a disposable TimescaleDB database."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from evolver.api.main import app
from evolver.ingestion.__main__ import store_v1_message
from evolver.ingestion.control import (
    expire_commands,
    invalidate_controls,
    pause_control,
    pending_commands,
    record_result,
)
from evolver_contracts.models import ExecutedCommandResult, ReceivedCommandResult, TelemetryEvent
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.mark.integration
def test_two_cycles_reordering_unknown_ending_and_experiment_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("EVOLVER_CONTROL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set EVOLVER_CONTROL_TEST_DATABASE_URL to a disposable TimescaleDB database")
    assert make_url(database_url).database.startswith("evolver_test_")
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("""
            TRUNCATE od_readings, pump_commands, pump_control, experiments
            RESTART IDENTITY CASCADE
        """))
    topic = "evolver/v1/evolver-sim-01/telemetry"

    def db_now() -> datetime:
        with engine.connect() as connection:
            return connection.scalar(text("SELECT clock_timestamp()"))

    def reading(
        experiment_id: int, value: float, sequence: int, generated_at: datetime,
        event_id: UUID | None = None, vial_id: int = 1,
    ) -> str:
        event = TelemetryEvent(
            schema_version="1.0", event_id=event_id or uuid4(), producer_id="simulator-local-01",
            equipment_id="evolver-sim-01", vial_id=str(vial_id),
            experiment_run_id=str(experiment_id), measurement_type="od", value=value,
            generated_at=generated_at, sequence=sequence,
        )
        return store_v1_message(engine, topic, event.model_dump_json().encode())

    def commands(experiment_id: int) -> list[dict]:
        with engine.connect() as connection:
            return list(connection.execute(text("""
                SELECT command_id, desired_state, result_status, reading_event_id,
                       sent_at, puback_at FROM pump_commands
                WHERE experiment_id = :id ORDER BY created_at
            """), {"id": experiment_id}).mappings())

    def executed(command_id) -> None:
        with engine.begin() as connection:
            record_result(connection, ExecutedCommandResult(
                schema_version="1.0", command_id=command_id,
                equipment_id="evolver-sim-01", simulated=True,
                status="executed", reported_at=datetime.now(UTC),
            ))

    with TestClient(app) as client:
        created = client.post("/api/experiments", json={
            "name": "Controle", "culture_type": "Levedura", "vial_id": 1,
            "od_min": 0.2, "od_max": 0.7,
        })
        assert created.status_code == 201
        experiment_id = created.json()["id"]
        now = db_now()
        with engine.begin() as connection:
            connection.execute(text("""
                UPDATE experiments SET started_at = :started_at WHERE id = :id
            """), {"started_at": now - timedelta(seconds=30), "id": experiment_id})
        first_event = uuid4()
        assert reading(experiment_id, 0.7, 1, now, first_event) == "gravada"
        assert reading(experiment_id, 0.7, 1, now, first_event) == "duplicada"
        first = commands(experiment_id)
        assert len(first) == 1 and first[0]["desired_state"] == "on"
        assert first[0]["reading_event_id"] is not None
        with engine.connect() as connection:
            queued = pending_commands(connection, datetime.now(UTC))
        assert len(queued) == 1
        assert queued[0].experiment_run_id == str(experiment_id)
        assert queued[0].pump_id == 1
        assert queued[0].action == "turn_on"
        assert first[0]["sent_at"] is None and first[0]["puback_at"] is None
        with engine.begin() as connection:
            connection.execute(text("""
                UPDATE pump_commands SET sent_at = :now, puback_at = :now
                WHERE command_id = :id
            """), {"now": db_now(), "id": first[0]["command_id"]})
            record_result(connection, ReceivedCommandResult(
                schema_version="1.0", command_id=first[0]["command_id"],
                equipment_id="evolver-sim-01", simulated=True,
                status="received", reported_at=datetime.now(UTC),
            ))
        with engine.connect() as connection:
            state = connection.execute(text("""
                SELECT confirmed_state, pending_command_id FROM pump_control
                WHERE experiment_id = :id
            """), {"id": experiment_id}).one()
        assert state == ("off", first[0]["command_id"])
        assert reading(experiment_id, 0.8, 2, now + timedelta(milliseconds=1)) == "gravada"
        assert len(commands(experiment_id)) == 1
        executed(first[0]["command_id"])
        assert reading(experiment_id, 0.2, 3, now + timedelta(milliseconds=2)) == "gravada"
        second = commands(experiment_id)[-1]
        assert second["desired_state"] == "off"
        executed(second["command_id"])
        assert reading(experiment_id, 0.7, 4, now + timedelta(milliseconds=3)) == "gravada"
        third = commands(experiment_id)[-1]
        assert third["desired_state"] == "on"
        executed(third["command_id"])
        assert reading(experiment_id, 0.2, 5, now + timedelta(milliseconds=4)) == "gravada"
        fourth = commands(experiment_id)[-1]
        assert fourth["desired_state"] == "off"
        executed(fourth["command_id"])
        assert [row["desired_state"] for row in commands(experiment_id)] == [
            "on", "off", "on", "off",
        ]
        # A late but valid historical event is stored without reversing the controller.
        assert reading(experiment_id, 0.8, 0, now - timedelta(seconds=1)) == "gravada"
        assert len(commands(experiment_id)) == 4
        assert reading(experiment_id, 0.7, 6, now - timedelta(seconds=11)) == "gravada"
        assert len(commands(experiment_id)) == 4
        assert reading(experiment_id, 0.8, 7, db_now()) == "gravada"
        fifth = commands(experiment_id)[-1]
        assert fifth["desired_state"] == "on"
        with engine.begin() as connection:
            expire_commands(connection, datetime.now(UTC) + timedelta(seconds=11))
        assert commands(experiment_id)[-1]["result_status"] == "unknown"
        assert reading(experiment_id, 0.2, 8, db_now()) == "gravada"
        assert len(commands(experiment_id)) == 5
        # Ending with unknown state requests a safe off command, then completes on execution.
        assert client.post(f"/api/experiments/{experiment_id}/inactivate").status_code == 200
        ending = commands(experiment_id)[-1]
        assert ending["desired_state"] == "off"
        executed(ending["command_id"])
        assert client.get(f"/api/experiments/{experiment_id}").json()["status"] == "inactive"
        replacement = client.post("/api/experiments", json={
            "name": "Novo", "culture_type": "Levedura", "vial_id": 1,
            "od_min": 0.2, "od_max": 0.7,
        })
        assert replacement.status_code == 201
        assert reading(experiment_id, 0.8, 9, now + timedelta(milliseconds=5)) == "gravada"
        assert len(commands(replacement.json()["id"])) == 0
        replacement_id = replacement.json()["id"]
        assert reading(replacement_id, 0.7, 1, db_now()) == "gravada"
        pending_on = commands(replacement_id)[-1]
        with engine.begin() as connection:
            pause_control(connection, replacement_id, datetime.now(UTC))
        executed(pending_on["command_id"])
        pending_off = commands(replacement_id)[-1]
        assert pending_off["desired_state"] == "off"
        executed(pending_off["command_id"])
        assert reading(replacement_id, 0.8, 2, db_now()) == "gravada"
        assert len(commands(replacement_id)) == 2
        with engine.begin() as connection:
            connection.execute(text("""
                UPDATE pump_control SET paused = false WHERE experiment_id = :id
            """), {"id": replacement_id})
        with ThreadPoolExecutor(max_workers=2) as pool:
            paused = pool.submit(lambda: _pause(engine, replacement_id))
            measured = pool.submit(reading, replacement_id, 0.7, 3, db_now())
            paused.result()
            assert measured.result() == "gravada"
        race_commands = commands(replacement_id)
        if len(race_commands) == 3:
            assert race_commands[-1]["desired_state"] == "on"
            executed(race_commands[-1]["command_id"])
            assert commands(replacement_id)[-1]["desired_state"] == "off"
        else:
            assert len(race_commands) == 2
        # A new backend connection sees the persisted pause and cannot reuse old OD.
        restarted = create_engine(database_url)
        with restarted.connect() as connection:
            assert connection.scalar(text("""
                SELECT paused FROM pump_control WHERE experiment_id = :id
            """), {"id": replacement_id})
        restarted.dispose()
        assert reading(replacement_id, 0.8, 4, db_now()) == "gravada"
        assert not any(row["desired_state"] == "on" for row in commands(replacement_id)[3:])
        pending_end = client.post("/api/experiments", json={
            "name": "Encerramento", "culture_type": "Levedura", "vial_id": 2,
            "od_min": 0.2, "od_max": 0.7,
        }).json()["id"]
        assert reading(pending_end, 0.7, 1, db_now(), vial_id=2) == "gravada"
        assert client.delete(f"/api/experiments/{pending_end}").status_code == 204
        assert len(commands(pending_end)) == 1
        with engine.begin() as connection:
            expire_commands(connection, datetime.now(UTC) + timedelta(seconds=11))
        safe_off = commands(pending_end)[-1]
        assert safe_off["desired_state"] == "off"
        executed(safe_off["command_id"])
        assert client.get(f"/api/experiments/{pending_end}").status_code == 404

        resumed_id = client.post("/api/experiments", json={
            "name": "Reconexão", "culture_type": "Levedura", "vial_id": 3,
            "od_min": 0.2, "od_max": 0.7,
        }).json()["id"]
        first_od_time = db_now()
        assert reading(resumed_id, 0.7, 1, first_od_time, vial_id=3) == "gravada"
        executed(commands(resumed_id)[-1]["command_id"])
        with engine.begin() as connection:
            invalidate_controls(connection)
        with engine.connect() as connection:
            assert connection.execute(text("""
                SELECT confirmed_state, reconcile_required FROM pump_control
                WHERE experiment_id = :id
            """), {"id": resumed_id}).one() == ("unknown", True)
        assert reading(resumed_id, 0.8, 1, first_od_time, vial_id=3) == "gravada"
        assert len(commands(resumed_id)) == 1
        assert reading(resumed_id, 0.8, 2, db_now(), vial_id=3) == "gravada"
        with engine.connect() as connection:
            assert connection.scalar(text("""
                SELECT reason FROM pump_commands WHERE command_id = :id
            """), {"id": commands(resumed_id)[-1]["command_id"]}) == "reconcile"
        assert commands(resumed_id)[-1]["desired_state"] == "off"
        executed(commands(resumed_id)[-1]["command_id"])
        assert reading(resumed_id, 0.8, 3, db_now(), vial_id=3) == "gravada"
        assert commands(resumed_id)[-1]["desired_state"] == "on"
        executed(commands(resumed_id)[-1]["command_id"])
        # A lower producer sequence means a simulator restart, even on the same MQTT session.
        assert reading(resumed_id, 0.8, 0, db_now(), vial_id=3) == "gravada"
        assert commands(resumed_id)[-1]["desired_state"] == "off"

        uncertain_id = client.post("/api/experiments", json={
            "name": "Pendente", "culture_type": "Levedura", "vial_id": 4,
            "od_min": 0.2, "od_max": 0.7,
        }).json()["id"]
        assert reading(uncertain_id, 0.7, 1, db_now(), vial_id=4) == "gravada"
        with engine.begin() as connection:
            invalidate_controls(connection)
            assert all(
                command.experiment_run_id != str(uncertain_id)
                for command in pending_commands(connection, datetime.now(UTC))
            )
        assert reading(uncertain_id, 0.8, 2, db_now(), vial_id=4) == "gravada"
        assert len(commands(uncertain_id)) == 1
        with engine.begin() as connection:
            expire_commands(connection, datetime.now(UTC) + timedelta(seconds=11))
        assert reading(uncertain_id, 0.8, 3, db_now(), vial_id=4) == "gravada"
        assert [row["desired_state"] for row in commands(uncertain_id)] == ["on", "off"]
        with engine.begin() as connection:
            expire_commands(connection, datetime.now(UTC) + timedelta(seconds=11))
        assert reading(uncertain_id, 0.8, 4, db_now(), vial_id=4) == "gravada"
        assert len(commands(uncertain_id)) == 2
    engine.dispose()


def _pause(engine, experiment_id: int) -> None:
    with engine.begin() as connection:
        pause_control(connection, experiment_id, datetime.now(UTC))
