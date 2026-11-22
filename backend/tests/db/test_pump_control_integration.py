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
    command_is_current,
    expire_commands,
    invalidate_controls,
    pause_control,
    pending_commands,
    queue_safety_offs,
    record_result,
)
from evolver_contracts.models import (
    ExecutedCommandResult,
    ReceivedCommandResult,
    RejectedCommandResult,
    TelemetryEvent,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url


@pytest.fixture
def control_database(monkeypatch: pytest.MonkeyPatch):
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
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.integration
def test_two_cycles_reordering_unknown_ending_and_experiment_isolation(
    control_database: Engine,
) -> None:
    engine = control_database
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

    def mark_sent(command_id) -> None:
        with engine.begin() as connection:
            connection.execute(text("""
                UPDATE pump_commands SET sent_at = clock_timestamp(), puback_at = clock_timestamp()
                WHERE command_id = :id
            """), {"id": command_id})

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
        assert client.post(f"/api/experiments/{experiment_id}/inactivate").status_code == 202
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
        pump_url = f"/api/experiments/{replacement_id}/pump"
        assert reading(replacement_id, 0.7, 1, db_now()) == "gravada"
        pending_on = commands(replacement_id)[-1]
        mark_sent(pending_on["command_id"])
        assert client.post(f"{pump_url}/pause").json()["state"] == "pausing"
        pending_off = commands(replacement_id)[-1]
        assert pending_off["desired_state"] == "off"
        assert commands(replacement_id)[0]["result_status"] == "superseded"
        assert client.post(f"{pump_url}/pause").json()["state"] == "pausing"
        executed(pending_on["command_id"])
        mark_sent(pending_off["command_id"])
        assert client.get(pump_url).json()["state"] == "pausing"
        with engine.begin() as connection:
            record_result(connection, ReceivedCommandResult(
                schema_version="1.0", command_id=pending_off["command_id"],
                equipment_id="evolver-sim-01", simulated=True,
                status="received", reported_at=datetime.now(UTC),
            ))
        assert client.get(pump_url).json()["state"] == "pausing"
        executed(pending_off["command_id"])
        assert client.get(pump_url).json()["state"] == "paused"
        assert reading(replacement_id, 0.8, 2, db_now()) == "gravada"
        assert len(commands(replacement_id)) == 2
        assert reading(replacement_id, 0.6, 3, db_now()) == "gravada"
        assert client.post(f"{pump_url}/resume").json()["state"] == "automatic"
        assert len(commands(replacement_id)) == 2
        with ThreadPoolExecutor(max_workers=2) as pool:
            paused = pool.submit(client.post, f"{pump_url}/pause")
            measured = pool.submit(reading, replacement_id, 0.7, 4, db_now())
            assert paused.result().json()["state"] == "paused"
            assert measured.result() == "gravada"
        race_commands = commands(replacement_id)
        assert all(row["result_status"] == "superseded" for row in race_commands[2:])
        assert reading(replacement_id, 0.8, 5, db_now()) == "gravada"
        assert commands(replacement_id) == race_commands
        pending_end = client.post("/api/experiments", json={
            "name": "Encerramento", "culture_type": "Levedura", "vial_id": 2,
            "od_min": 0.2, "od_max": 0.7,
        }).json()["id"]
        assert reading(pending_end, 0.7, 1, db_now(), vial_id=2) == "gravada"
        assert client.delete(f"/api/experiments/{pending_end}").status_code == 202
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

        def create_controlled(vial_id: int) -> int:
            response = client.post("/api/experiments", json={
                "name": f"Seguro {vial_id}", "culture_type": "Levedura", "vial_id": vial_id,
                "od_min": 0.2, "od_max": 0.7,
            })
            assert response.status_code == 201
            return response.json()["id"]

        def ready_off(experiment_id: int) -> None:
            with engine.connect() as connection:
                assert any(
                    command.experiment_run_id == str(experiment_id)
                    and command.action == "turn_off"
                    for command in pending_commands(connection, datetime.now(UTC))
                )

        paused_id = create_controlled(5)
        assert reading(paused_id, 0.7, 1, db_now(), vial_id=5) == "gravada"
        executed(commands(paused_id)[-1]["command_id"])
        with engine.begin() as connection:
            invalidate_controls(connection)
            pause_control(connection, paused_id, datetime.now(UTC))
        ready_off(paused_id)
        executed(commands(paused_id)[-1]["command_id"])
        with engine.connect() as connection:
            assert connection.execute(text("""
                SELECT confirmed_state, reconcile_required, paused FROM pump_control
                WHERE experiment_id = :id
            """), {"id": paused_id}).one() == ("off", False, True)

        ending_id = create_controlled(6)
        assert reading(ending_id, 0.7, 1, db_now(), vial_id=6) == "gravada"
        executed(commands(ending_id)[-1]["command_id"])
        with engine.begin() as connection:
            invalidate_controls(connection)
        assert client.post(f"/api/experiments/{ending_id}/inactivate").status_code == 202
        ready_off(ending_id)
        executed(commands(ending_id)[-1]["command_id"])
        assert client.get(f"/api/experiments/{ending_id}").json()["status"] == "inactive"
        assert 6 in [item["vial_id"] for item in client.get("/api/vials/available").json()]

        prior_off_id = create_controlled(7)
        assert reading(prior_off_id, 0.7, 1, db_now(), vial_id=7) == "gravada"
        executed(commands(prior_off_id)[-1]["command_id"])
        assert reading(prior_off_id, 0.2, 2, db_now(), vial_id=7) == "gravada"
        old_off = commands(prior_off_id)[-1]["command_id"]
        with engine.begin() as connection:
            invalidate_controls(connection)
        assert client.delete(f"/api/experiments/{prior_off_id}").status_code == 202
        assert commands(prior_off_id)[-1]["command_id"] == old_off
        ready_off(prior_off_id)
        with engine.begin() as connection:
            record_result(connection, ReceivedCommandResult(
                schema_version="1.0", command_id=old_off,
                equipment_id="evolver-sim-01", simulated=True,
                status="received", reported_at=datetime.now(UTC),
            ))
        assert client.get(f"/api/experiments/{prior_off_id}").json()["status"] == "active"
        executed(old_off)
        assert client.get(f"/api/experiments/{prior_off_id}").status_code == 404
        assert 7 in [item["vial_id"] for item in client.get("/api/vials/available").json()]

        pending_pause_id = create_controlled(8)
        assert reading(pending_pause_id, 0.7, 1, db_now(), vial_id=8) == "gravada"
        pending_on = commands(pending_pause_id)[-1]["command_id"]
        with engine.begin() as connection:
            invalidate_controls(connection)
            pause_control(connection, pending_pause_id, datetime.now(UTC))
            assert all(
                command.experiment_run_id != str(pending_pause_id) or command.action == "turn_off"
                for command in pending_commands(connection, datetime.now(UTC))
            )
        executed(pending_on)
        ready_off(pending_pause_id)
        executed(commands(pending_pause_id)[-1]["command_id"])

        pending_end_id = create_controlled(9)
        assert reading(pending_end_id, 0.7, 1, db_now(), vial_id=9) == "gravada"
        with engine.begin() as connection:
            invalidate_controls(connection)
        assert client.post(f"/api/experiments/{pending_end_id}/inactivate").status_code == 202
        with engine.begin() as connection:
            expire_commands(connection, datetime.now(UTC) + timedelta(seconds=11))
        ready_off(pending_end_id)
        executed(commands(pending_end_id)[-1]["command_id"])
        assert client.get(f"/api/experiments/{pending_end_id}").json()["status"] == "inactive"

        reconnect_pause_id = create_controlled(10)
        with engine.begin() as connection:
            pause_control(connection, reconnect_pause_id, datetime.now(UTC))
            invalidate_controls(connection)
            queue_safety_offs(connection, datetime.now(UTC))
        ready_off(reconnect_pause_id)
        executed(commands(reconnect_pause_id)[-1]["command_id"])

        sent_off_id = create_controlled(11)
        assert reading(sent_off_id, 0.7, 1, db_now(), vial_id=11) == "gravada"
        executed(commands(sent_off_id)[-1]["command_id"])
        assert reading(sent_off_id, 0.2, 2, db_now(), vial_id=11) == "gravada"
        old_sent_off = commands(sent_off_id)[-1]["command_id"]
        with engine.begin() as connection:
            connection.execute(text("""
                UPDATE pump_commands SET sent_at = :now WHERE command_id = :id
            """), {"now": datetime.now(UTC), "id": old_sent_off})
            invalidate_controls(connection)
        assert client.delete(f"/api/experiments/{sent_off_id}").status_code == 202
        with engine.begin() as connection:
            expire_commands(connection, datetime.now(UTC) + timedelta(seconds=11))
        assert commands(sent_off_id)[-1]["command_id"] != old_sent_off
        ready_off(sent_off_id)
        executed(commands(sent_off_id)[-1]["command_id"])
        assert client.get(f"/api/experiments/{sent_off_id}").status_code == 404

        pause_id = create_controlled(12)
        base = f"/api/experiments/{pause_id}"

        def set_mode(action: str, state: str, *, path: str = base) -> None:
            response = client.post(f"{path}/pump/{action}")
            assert response.status_code == 200
            assert response.json()["state"] == state

        # Pausing and resuming before the first reading leaves the outbox empty.
        set_mode("pause", "paused")
        set_mode("pause", "paused")
        set_mode("resume", "automatic")
        set_mode("resume", "automatic")
        assert commands(pause_id) == []

        # Resume at the threshold, then cancel a queued on order before publication.
        set_mode("pause", "paused")
        assert reading(pause_id, 0.7, 1, db_now(), vial_id=12) == "gravada"
        set_mode("resume", "automatic")
        on = commands(pause_id)[-1]
        assert on["desired_state"] == "on" and on["reading_event_id"] is not None
        set_mode("resume", "automatic")
        assert commands(pause_id) == [on]
        with engine.connect() as connection:
            batched_on = next(c for c in pending_commands(connection, db_now())
                              if c.command_id == on["command_id"])
        set_mode("pause", "paused")
        with engine.begin() as connection:
            assert not command_is_current(connection, batched_on, db_now())
        assert [row["result_status"] for row in commands(pause_id)] == ["superseded"]
        set_mode("resume", "automatic")
        executed(commands(pause_id)[-1]["command_id"])
        set_mode("pause", "pausing")
        ready_off(pause_id)
        off = commands(pause_id)[-1]
        assert off["desired_state"] == "off" and off["reading_event_id"] is None
        with engine.begin() as connection:
            record_result(connection, RejectedCommandResult(
                schema_version="1.0", command_id=off["command_id"],
                equipment_id="evolver-sim-01", simulated=True, status="rejected",
                reason_code="invalid_payload", reported_at=datetime.now(UTC),
            ))
        set_mode("pause", "off_unconfirmed")
        assert reading(pause_id, 0.8, 2, db_now(), vial_id=12) == "gravada"
        assert len(commands(pause_id)) == 3
        # MQTT reconnection reconciles the persisted pause without OD.
        with engine.begin() as connection:
            invalidate_controls(connection)
            queue_safety_offs(connection, db_now())
        assert client.get(f"{base}/pump").json()["state"] == "pausing"
        executed(commands(pause_id)[-1]["command_id"])

        assert reading(pause_id, 0.81, 3, db_now(), vial_id=12) == "gravada"
        set_mode("resume", "automatic")
        assert len(commands(pause_id)) == 4
        assert client.post(f"{base}/inactivate").status_code == 200
        assert client.post(f"{base}/pump/resume").status_code == 409
        new_id = create_controlled(12)
        new_base = f"/api/experiments/{new_id}"
        assert client.get(f"{new_base}/pump").json()["state"] == "automatic"
        set_mode("pause", "paused", path=new_base)
        set_mode("resume", "automatic", path=new_base)
        assert commands(new_id) == []

        set_mode("pause", "paused", path=new_base)
        now = db_now()
        with engine.begin() as connection:
            connection.execute(text("""
                UPDATE experiments SET started_at = :before WHERE id = :id
            """), {"id": new_id, "before": now - timedelta(seconds=30)})
        assert reading(new_id, 0.8, 1, now - timedelta(seconds=11), vial_id=12) == "gravada"
        set_mode("resume", "automatic", path=new_base)
        assert commands(new_id) == []

        assert reading(new_id, 0.8, 2, db_now(), vial_id=12) == "gravada"
        mark_sent(commands(new_id)[-1]["command_id"])
        set_mode("pause", "pausing", path=new_base)
        with engine.begin() as connection:
            expire_commands(connection, db_now() + timedelta(seconds=11))
        assert client.get(f"{new_base}/pump").json()["state"] == "off_unconfirmed"
    with TestClient(app) as restarted:
        assert restarted.get(f"{new_base}/pump").json()["state"] == "off_unconfirmed"


class PumpRun:
    def __init__(self, engine: Engine, client: TestClient) -> None:
        self.engine = engine
        self.client = client
        response = client.post("/api/experiments", json={
            "name": "Retomada", "culture_type": "Simulada", "vial_id": 1,
            "od_min": 0.2, "od_max": 0.7,
        })
        assert response.status_code == 201
        self.id = response.json()["id"]
        self.url = f"/api/experiments/{self.id}/pump"

    def now(self) -> datetime:
        with self.engine.connect() as connection:
            return connection.scalar(text("SELECT clock_timestamp()"))

    def mode(self, action: str, state: str) -> None:
        response = self.client.post(f"{self.url}/{action}")
        assert response.status_code == 200
        assert response.json()["state"] == state

    def od(self, value: float, sequence: int, generated_at: datetime) -> UUID:
        event = TelemetryEvent(
            schema_version="1.0", event_id=uuid4(), producer_id="simulator-local-01",
            equipment_id="evolver-sim-01", vial_id="1", experiment_run_id=str(self.id),
            measurement_type="od", value=value, generated_at=generated_at, sequence=sequence,
        )
        assert store_v1_message(
            self.engine, "evolver/v1/evolver-sim-01/telemetry", event.model_dump_json().encode(),
        ) == "gravada"
        return event.event_id

    def queued(self):
        with self.engine.connect() as connection:
            return pending_commands(connection, self.now())

    def result(self, command_id: UUID, *, rejected: bool = False) -> None:
        fields = dict(schema_version="1.0", command_id=command_id,
                      equipment_id="evolver-sim-01", simulated=True, reported_at=self.now())
        result = (
            RejectedCommandResult(status="rejected", reason_code="invalid_payload", **fields)
            if rejected else ExecutedCommandResult(status="executed", **fields)
        )
        with self.engine.begin() as connection:
            record_result(connection, result)


@pytest.mark.integration
@pytest.mark.parametrize("scenario", [
    "lower_before_claim", "lower_after_claim", "stale_after_claim",
    "expired_unsent", "stale_previous_claim",
])
def test_resume_on_revalidates_od_before_publication(
    control_database: Engine, scenario: str,
) -> None:
    with TestClient(app) as client:
        run = PumpRun(control_database, client)
        run.mode("pause", "paused")
        generated_at = run.now() - timedelta(seconds=2)
        with run.engine.begin() as connection:
            connection.execute(text("""
                UPDATE experiments SET started_at = :at WHERE id = :id
            """), {"at": generated_at, "id": run.id})
        run.od(0.7, 1, generated_at)
        run.mode("resume", "automatic")
        turn_on, = run.queued()
        assert turn_on.action == "turn_on"
        if scenario not in ("lower_before_claim", "expired_unsent"):
            with run.engine.begin() as connection:
                assert command_is_current(connection, turn_on)
                connection.execute(text("""
                    UPDATE pump_commands SET sent_at = clock_timestamp() WHERE command_id = :id
                """), {"id": turn_on.command_id})
        if scenario.startswith("lower"):
            run.od(0.2, 2, run.now())
        with run.engine.begin() as connection:
            if scenario != "expired_unsent":
                checked_at = run.now()
                if scenario.startswith("stale"):
                    checked_at = generated_at + timedelta(seconds=10, microseconds=1)
                    assert checked_at < turn_on.expires_at
                assert not command_is_current(
                    connection, turn_on, checked_at,
                    claimed_here=scenario in ("lower_after_claim", "stale_after_claim"),
                )
            expire_commands(connection, turn_on.expires_at + timedelta(microseconds=1))
            actual = connection.execute(text("""
                SELECT p.result_status, p.sent_at IS NOT NULL, c.confirmed_state,
                       c.pending_command_id, c.reconcile_required
                FROM pump_commands p JOIN pump_control c ON c.experiment_id = p.experiment_id
                WHERE p.command_id = :id
            """), {"id": turn_on.command_id}).one()
        expected = ("superseded", False, "off", None, False)
        if scenario == "stale_previous_claim":
            expected = ("unknown", True, "unknown", None, True)
        assert actual == expected
        assert run.queued() == []


@pytest.mark.integration
@pytest.mark.parametrize("od, failure", [(0.6, "none"), (0.7, "none"), (0.7, "before"),
                                         (0.7, "after")])
def test_resumption_persists_and_evaluates_od_when_off_executes(
    control_database: Engine, od: float, failure: str,
) -> None:
    with TestClient(app) as client:
        run = PumpRun(control_database, client)
        run.od(0.7, 1, run.now())
        turn_on, = run.queued()
        run.result(turn_on.command_id)
        with run.engine.begin() as connection:
            pause_control(connection, run.id, turn_on.created_at - timedelta(seconds=1))
        turn_off, = run.queued()
        assert turn_off.action == "turn_off" and turn_off.created_at > turn_on.created_at
        with run.engine.begin() as connection:
            connection.execute(text("""
                UPDATE pump_commands SET sent_at = clock_timestamp() WHERE command_id = :id
            """), {"id": turn_off.command_id})
        if failure == "before":
            run.result(turn_off.command_id, rejected=True)
            assert client.get(run.url).json()["state"] == "off_unconfirmed"
        run.mode("resume", "resuming")
        run.mode("resume", "resuming")
        if failure == "after":
            run.result(turn_off.command_id, rejected=True)
        if failure != "none":
            replacement, = run.queued()
            assert replacement.action == "turn_off"
            assert replacement.command_id != turn_off.command_id
            turn_off = replacement
        else:
            assert run.queued() == []
        run.od(od, 2, run.now())
    with TestClient(app) as restarted:
        assert restarted.get(run.url).json()["state"] == "resuming"
        run.result(turn_off.command_id)
        assert restarted.get(run.url).json()["state"] == "automatic"
        assert [item.action for item in run.queued()] == (["turn_on"] if od >= 0.7 else [])


@pytest.mark.integration
@pytest.mark.parametrize("case", [
    "older_sequence", "same_identity", "invalid_newer", "future", "reused_vial",
])
def test_resume_uses_exact_accepted_od_cursor(control_database: Engine, case: str) -> None:
    with TestClient(app) as client:
        run = PumpRun(control_database, client)
        run.mode("pause", "paused")
        timestamp = run.now()
        accepted_id = run.od(0.7, 2, timestamp)
        if case == "older_sequence":
            run.od(0.2, 1, timestamp)
        elif case == "same_identity":
            run.od(0.2, 2, timestamp)
        elif case == "invalid_newer":
            run.od(0.81, 3, timestamp)
        elif case == "future":
            with pytest.raises(ValueError, match="experimento ativo"):
                run.od(0.2, 3, timestamp + timedelta(seconds=5))
        else:
            previous = run
            inactive = client.post(previous.url.removesuffix("/pump") + "/inactivate")
            assert inactive.json()["status"] == "inactive"
            run = PumpRun(control_database, client)
            run.mode("pause", "paused")
            previous.od(0.8, 3, timestamp)
        run.mode("resume", "automatic")
        with run.engine.connect() as connection:
            actual = connection.execute(text("""
                SELECT reading_event_id FROM pump_commands WHERE experiment_id = :id
            """), {"id": run.id}).scalars().all()
        assert actual == ([] if case in ("invalid_newer", "reused_vial") else [accepted_id])



@pytest.mark.integration
@pytest.mark.parametrize("action", ["inactivate", "delete"])
@pytest.mark.parametrize("pump_state", ["off", "on", "uncertain"])
def test_closure_status_retry_and_persistence(
    control_database: Engine, action: str, pump_state: str,
) -> None:
    engine = control_database
    with TestClient(app) as client:
        run = PumpRun(engine, client)
        base = run.url.removesuffix("/pump")
        status_url = f"{base}/closure"
        if pump_state == "on":
            run.od(0.7, 1, run.now())
            run.result(run.queued()[0].command_id)
        elif pump_state == "uncertain":
            with engine.begin() as connection:
                connection.execute(text("""
                    UPDATE pump_control SET reconcile_required = true WHERE experiment_id = :id
                """), {"id": run.id})
        assert client.get(status_url).json()["state"] == "none"

        def close_experiment(api: TestClient):
            return api.delete(base) if action == "delete" else api.post(f"{base}/inactivate")

        def vial_available(api: TestClient) -> bool:
            return 1 in {vial["vial_id"] for vial in api.get("/api/vials/available").json()}

        immediate_status = 204 if action == "delete" else 200
        requested = close_experiment(client)
        if pump_state == "off":
            assert requested.status_code == immediate_status
            assert not run.queued()
        else:
            assert requested.status_code == 202
            assert requested.json() == {"state": "pending", "action": action, "ended_at": None}
            first, = run.queued()
            assert first.action == "turn_off"
            assert client.get(base).json()["status"] == "active"
            assert not vial_available(client)
            assert close_experiment(client).status_code == 202
            assert run.queued() == [first]
            with engine.begin() as connection:
                connection.execute(text("""
                    UPDATE pump_commands SET sent_at = now(), puback_at = now()
                    WHERE command_id = :id
                """), {"id": first.command_id})
                record_result(connection, ReceivedCommandResult(
                    schema_version="1.0", command_id=first.command_id,
                    equipment_id="evolver-sim-01", simulated=True,
                    status="received", reported_at=run.now(),
                ))
            assert client.get(status_url).json()["state"] == "pending"
            assert not vial_available(client)

            if pump_state == "on":
                run.result(first.command_id, rejected=True)
            else:
                # Mimic a stopped ingestor: the deadline passes before the worker can sweep.
                with engine.begin() as connection:
                    connection.execute(text("""
                        UPDATE pump_commands SET expires_at = now() - interval '1 second'
                        WHERE command_id = :id
                    """), {"id": first.command_id})

            with TestClient(app) as restarted:
                assert restarted.get(status_url).json()["state"] == "unconfirmed"
                assert not vial_available(restarted)
                assert close_experiment(restarted).status_code == 202
                retry, = run.queued()
                assert retry.action == "turn_off" and retry.command_id != first.command_id
                assert close_experiment(restarted).status_code == 202
                assert run.queued() == [retry]
                run.result(first.command_id)  # Late success for a superseded attempt.
                assert restarted.get(status_url).json()["state"] == "pending"
                assert not vial_available(restarted)
                run.result(retry.command_id)

        result = client.get(status_url).json()
        assert result["state"] == "completed" and result["action"] == action and result["ended_at"]
        assert vial_available(client)
        assert close_experiment(client).status_code == immediate_status
        visible = client.get("/api/experiments").json()
        if action == "delete":
            assert client.get(base).status_code == 404
            assert visible == []
        else:
            assert client.get(base).json()["status"] == "inactive"
            assert [experiment["status"] for experiment in visible] == ["inactive"]
        with engine.connect() as connection:
            ended, deleted = connection.execute(text("""
                SELECT ended_at, deleted_at FROM experiments WHERE id = :id
            """), {"id": run.id}).one()
            assert ended is not None
            assert (deleted is not None) == (action == "delete")
            if pump_state == "on":
                assert connection.scalar(text("SELECT count(*) FROM od_readings")) == 1


@pytest.mark.integration
def test_ending_between_resume_claim_and_publish_queues_off(control_database: Engine) -> None:
    engine = control_database
    with TestClient(app) as client:
        run = PumpRun(engine, client)
        run.mode("pause", "paused")
        run.od(0.7, 1, run.now())
        run.mode("resume", "automatic")
        on, = run.queued()
        assert on.action == "turn_on"
        with engine.begin() as connection:
            assert command_is_current(connection, on)
            connection.execute(text("""
                UPDATE pump_commands SET sent_at = now() WHERE command_id = :id
            """), {"id": on.command_id})
        base = run.url.removesuffix("/pump")
        assert client.post(f"{base}/inactivate").status_code == 202
        with engine.begin() as connection:
            assert not command_is_current(connection, on, claimed_here=True)
            expire_commands(connection, on.expires_at)
        off, = run.queued()
        assert off.action == "turn_off"
        run.result(off.command_id)
        assert client.get(base).json()["status"] == "inactive"


@pytest.mark.integration
def test_ending_does_not_retry_failed_off_from_od(control_database: Engine) -> None:
    engine = control_database
    with TestClient(app) as client:
        run = PumpRun(engine, client)
        run.od(0.7, 1, run.now())
        run.result(run.queued()[0].command_id)
        base = run.url.removesuffix("/pump")
        assert client.delete(base).status_code == 202
        off, = run.queued()
        with engine.begin() as connection:
            invalidate_controls(connection)
            expire_commands(connection, off.expires_at)
        assert client.get(f"{base}/closure").json()["state"] == "unconfirmed"
        run.od(0.7, 0, run.now() + timedelta(microseconds=1))
        assert not run.queued()
        with engine.begin() as connection:
            invalidate_controls(connection)
            queue_safety_offs(connection, run.now())
        retry, = run.queued()
        assert retry.command_id != off.command_id
        run.result(retry.command_id)
        assert client.get(f"{base}/closure").json()["state"] == "completed"
