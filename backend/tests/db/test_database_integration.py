from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from evolver.db.queries import get_temperature_history
from evolver.ingestion.__main__ import store_message
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


@pytest.mark.integration
def test_temperature_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("EVOLVER_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set EVOLVER_TEST_DATABASE_URL to a disposable TimescaleDB database")

    monkeypatch.setenv("DATABASE_URL", database_url)
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM timescaledb_information.hypertables "
                    "WHERE hypertable_name = 'temperature_readings'"
                )
            ).scalar_one()
            == 1
        )
        vial_id = connection.execute(
            text(
                "INSERT INTO vials (equipment_id, created_at) "
                "VALUES ('evolver-sim-01', now()) RETURNING vial_id"
            )
        ).scalar_one()

    message = {
        "equipment_id": "evolver-sim-01",
        "event_id": str(uuid4()),
        "vial_id": vial_id,
        "measurement": "temperature",
        "value": 37.0,
        "unit": "celsius",
        "generated_at": datetime.now(UTC).isoformat(),
    }
    payload = json.dumps(message).encode()
    topic = "evolver/dev/evolver-sim-01/telemetry"
    assert store_message(engine, topic, payload) == "gravada"
    assert store_message(engine, topic, payload) == "duplicada"
    with pytest.raises(ValueError, match="topic"):
        store_message(engine, "evolver/dev/another/telemetry", payload)
    with pytest.raises(ValueError, match="unknown"):
        store_message(engine, topic, json.dumps({**message, "vial_id": 999999}).encode())
    with Session(engine) as session:
        history = get_temperature_history(session, vial_id)
        assert len(history) == 1
        assert history[0].temperature_celsius == 37.0
    with engine.begin() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM temperature_readings WHERE event_id = :event_id"),
                {"event_id": message["event_id"]},
            ).scalar_one()
            == 1
        )
        row = connection.execute(
            text(
                "SELECT vial_id, temperature_celsius, generated_at, received_at "
                "FROM temperature_readings WHERE event_id = :event_id"
            ),
            {"event_id": message["event_id"]},
        ).one()
        assert row.vial_id == vial_id
        assert row.temperature_celsius == 37.0
        assert row.generated_at <= row.received_at
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
