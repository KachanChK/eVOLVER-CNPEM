from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from evolver.api.main import app
from evolver.ingestion.__main__ import active_vials, store_message, store_v1_message
from evolver_contracts.pilot import TELEMETRY_TOPIC
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


@pytest.mark.integration
def test_temperature_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("EVOLVER_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set EVOLVER_TEST_DATABASE_URL to a disposable TimescaleDB database")

    monkeypatch.setenv("DATABASE_URL", database_url)
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    command.upgrade(config, "20261111_02")
    engine = create_engine(database_url)
    # Populate the old combined table before migrating, then compare every field.
    historical_ids = {"ph": uuid4(), "od": uuid4()}
    historical_time = datetime.now(UTC)
    with engine.begin() as connection:
        historical_experiment = connection.scalar(
            text("""
                INSERT INTO experiments (name, vial_id, started_at, ended_at, deleted_at)
                VALUES ('Anterior', 1, now(), now(), now()) RETURNING id
            """)
        )
        for kind, value in (("ph", 7.25), ("od", 0.47)):
            connection.execute(
                text("""
                    INSERT INTO other_readings
                    (event_id, generated_at, received_at, vial_id, experiment_id,
                     measurement_type, value)
                    VALUES (:id, :time, :time, 1, :experiment, :kind, :value)
                """),
                {
                    "id": historical_ids[kind],
                    "time": historical_time,
                    "experiment": historical_experiment,
                    "kind": kind,
                    "value": value,
                },
            )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        for kind, value in (("ph", 7.25), ("od", 0.47)):
            row = connection.execute(
                text(f"""
                    SELECT event_id, generated_at, received_at, vial_id, experiment_id, {kind}_value
                    FROM {kind}_readings WHERE event_id = :id
                """),
                {"id": historical_ids[kind]},
            ).one()
            assert tuple(row) == (
                historical_ids[kind],
                historical_time,
                historical_time,
                1,
                historical_experiment,
                value,
            )
        assert connection.scalar(text("SELECT to_regclass('public.other_readings')")) is None
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM timescaledb_information.hypertables "
                    "WHERE hypertable_name = 'temperature_readings'"
                )
            ).scalar_one()
            == 1
        )
    request = json.dumps({"request_id": str(uuid4())}).encode()

    with TestClient(app) as client:

        def create(vial: int):
            return client.post("/api/experiments", json={"name": f"Teste {vial}", "vial_id": vial})

        def database_time():
            with engine.connect() as connection:
                return connection.scalar(text("SELECT clock_timestamp()")).isoformat()

        def free_ids():
            return [vial["vial_id"] for vial in client.get("/api/vials/available").json()]

        assert free_ids() == list(range(1, 13))
        assert active_vials(engine, request).vials == []
        assert client.post("/api/experiments", json={"name": " ", "vial_id": 1}).status_code == 422

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(create, [1, 1]))
        assert sorted(attempt.status_code for attempt in attempts) == [201, 409]
        first = next(attempt.json() for attempt in attempts if attempt.status_code == 201)
        first_url = f"/api/experiments/{first['id']}"
        assert client.get(first_url).json() == first
        assert free_ids() == list(range(2, 13))
        assert [vial.experiment_id for vial in active_vials(engine, request).vials] == [first["id"]]
        assert client.get(f"{first_url}/temperature-readings").json() == []
        assert all(create(vial).status_code == 201 for vial in range(2, 13))
        assert free_ids() == []

        message = {
            "equipment_id": "evolver-sim-01",
            "event_id": str(uuid4()),
            "vial_id": 1,
            "experiment_id": first["id"],
            "measurement": "temperature",
            "value": 37.0,
            "unit": "celsius",
            "generated_at": database_time(),
        }
        assert client.post(f"{first_url}/inactivate").json()["status"] == "inactive"
        assert free_ids() == [1]
        second = create(1).json()
        second_url = f"/api/experiments/{second['id']}"
        payload = json.dumps(message).encode()
        assert store_message(engine, TELEMETRY_TOPIC, payload) == "gravada"
        assert store_message(engine, TELEMETRY_TOPIC, payload) == "duplicada"
        with pytest.raises(ValueError, match="topic"):
            store_message(engine, "evolver/dev/another/telemetry", payload)
        with pytest.raises(ValueError, match="alocação"):
            store_message(engine, TELEMETRY_TOPIC, json.dumps({**message, "vial_id": 2}).encode())
        assert client.get(f"{second_url}/temperature-readings").json() == []
        newer = {**message, "event_id": str(uuid4()), "generated_at": database_time()}
        with pytest.raises(ValueError, match="alocação"):
            store_message(engine, TELEMETRY_TOPIC, json.dumps(newer).encode())
        newer["experiment_id"] = second["id"]
        assert store_message(engine, TELEMETRY_TOPIC, json.dumps(newer).encode()) == "gravada"
        assert [r["event_id"] for r in client.get(f"{first_url}/temperature-readings").json()] == [
            message["event_id"]
        ]
        assert [r["event_id"] for r in client.get(f"{second_url}/temperature-readings").json()] == [
            newer["event_id"]
        ]
        v1_topic = "evolver/v1/evolver-sim-01/telemetry"
        v1 = {
            "schema_version": "1.0",
            "event_id": str(uuid4()),
            "producer_id": "simulator-local-01",
            "equipment_id": "evolver-sim-01",
            "vial_id": "1",
            "measurement_type": "ph",
            "value": 7.1,
            "generated_at": message["generated_at"],
            "sequence": 1,
        }
        # A delayed reading must stay with the old experiment after vial reuse.
        assert store_v1_message(engine, v1_topic, json.dumps(v1).encode()) == "gravada"
        assert store_v1_message(engine, v1_topic, json.dumps(v1).encode()) == "duplicada"
        assert client.get(f"{first_url}/readings/ph").json()[0]["value"] == 7.1
        assert client.get(f"{second_url}/readings/ph").json() == []
        with pytest.raises(ValueError, match="experimento ativo"):
            store_v1_message(
                engine,
                v1_topic,
                json.dumps(
                    {
                        **v1,
                        "experiment_run_id": str(first["id"]),
                        "generated_at": newer["generated_at"],
                    }
                ).encode(),
            )
        for kind, value in [("od", 0.42), ("temperature", 36.8)]:
            event = {
                **v1,
                "event_id": str(uuid4()),
                "measurement_type": kind,
                "value": value,
                "generated_at": newer["generated_at"],
            }
            assert store_v1_message(engine, v1_topic, json.dumps(event).encode()) == "gravada"
        assert client.get(f"{second_url}/readings/od").json()[0]["value"] == 0.42
        assert 36.8 in [
            row["temperature_celsius"]
            for row in client.get(f"{second_url}/temperature-readings").json()
        ]
        with pytest.raises(ValueError):
            store_v1_message(engine, v1_topic, json.dumps({**v1, "vial_id": "99"}).encode())
        assert client.delete(first_url).status_code == 204
        assert client.delete(second_url).status_code == 204
        assert client.get(second_url).status_code == 404
        assert client.get(f"{second_url}/temperature-readings").status_code == 404
        assert free_ids() == [1]
        assert len(client.get("/api/experiments").json()) == 11
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM temperature_readings")) == 3
            assert connection.scalar(text("SELECT count(*) FROM ph_readings")) == 2
            assert connection.scalar(text("SELECT count(*) FROM od_readings")) == 2
    engine.dispose()


@pytest.mark.integration
def test_simplification_refuses_existing_data(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("EVOLVER_TEST_GUARD_DATABASE_URL")
    if not database_url:
        pytest.skip("set EVOLVER_TEST_GUARD_DATABASE_URL to another disposable database")
    monkeypatch.setenv("DATABASE_URL", database_url)
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    command.upgrade(config, "20261027_01")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO equipment (id, created_at) VALUES (:id, now())"),
            {"id": str(uuid4())},
        )
    with pytest.raises(Exception, match="contains data"):
        command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM equipment")).scalar_one() >= 1
    engine.dispose()
