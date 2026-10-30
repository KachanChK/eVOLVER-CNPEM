from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from evolver.db.models import (
    Command,
    Culture,
    Equipment,
    ExperimentRun,
    Measurement,
    Position,
    ProcessedEvent,
)
from evolver.db.queries import get_current_measurements, get_measurement_history

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_migration_quarantine_and_measurement_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.getenv("EVOLVER_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set EVOLVER_TEST_DATABASE_URL to a disposable TimescaleDB database")

    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            now = datetime.now(UTC)
            older_at = now - timedelta(seconds=1)
            equipment_id = f"test-{uuid4()}"
            position_id = uuid4()
            older_event_id = uuid4()
            latest_event_id = uuid4()
            quarantined_event_id = uuid4()
            culture_id = uuid4()
            run_id = f"run-{uuid4()}"

            with Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
            ) as session:
                session.add(Equipment(id=equipment_id, created_at=now))
                session.add(
                    Position(
                        id=position_id,
                        equipment_id=equipment_id,
                        position_code="A1",
                        vial_id=f"vial-{uuid4()}",
                        created_at=now,
                    )
                )
                # Filhos antes dos pais: o flush precisa reordenar pelas relationships.
                session.add_all(
                    [
                        Command(
                            command_id=uuid4(),
                            equipment_id=equipment_id,
                            experiment_run_id=run_id,
                            author_id="integration-test",
                            target_type="position",
                            target_id=str(position_id),
                            action="noop",
                            status="requested",
                            created_at=now,
                            expires_at=now + timedelta(minutes=1),
                            updated_at=now,
                        ),
                        ExperimentRun(
                            id=run_id,
                            equipment_id=equipment_id,
                            position_id=position_id,
                            culture_id=culture_id,
                            started_at=older_at,
                        ),
                        Culture(id=culture_id, vial_id=f"vial-{uuid4()}", created_at=now),
                        ProcessedEvent(
                            event_id=older_event_id,
                            equipment_id=equipment_id,
                            producer_id="integration-test",
                            generated_at=older_at,
                            received_at=now,
                        ),
                        ProcessedEvent(
                            event_id=latest_event_id,
                            equipment_id=equipment_id,
                            producer_id="integration-test",
                            generated_at=now,
                            received_at=now,
                        ),
                        ProcessedEvent(
                            event_id=quarantined_event_id,
                            equipment_id="unknown-equipment",
                            received_at=now,
                            outcome="quarantined",
                        ),
                        Measurement(
                            event_id=older_event_id,
                            generated_at=older_at,
                            received_at=now,
                            equipment_id=equipment_id,
                            position_id=position_id,
                            producer_id="integration-test",
                            sequence=1,
                            measurement_type="od",
                            value=0.25,
                            schema_version="1.0",
                        ),
                        Measurement(
                            event_id=latest_event_id,
                            generated_at=now,
                            received_at=now,
                            equipment_id=equipment_id,
                            position_id=position_id,
                            experiment_run_id=run_id,
                            producer_id="integration-test",
                            sequence=2,
                            measurement_type="od",
                            value=0.5,
                            schema_version="1.0",
                        ),
                    ]
                )
                session.flush()

                current_unfiltered = get_current_measurements(session)
                current_filtered = get_current_measurements(
                    session,
                    equipment_id=equipment_id,
                    position_id=position_id,
                    measurement_type="od",
                )
                history_unfiltered = get_measurement_history(session)
                history_filtered = get_measurement_history(
                    session,
                    equipment_id=equipment_id,
                    position_id=position_id,
                    measurement_type="od",
                    since=older_at,
                    until=now + timedelta(seconds=1),
                )

                assert isinstance(current_unfiltered, list)
                assert len(current_filtered) == 1
                assert current_filtered[0]["event_id"] == latest_event_id
                assert isinstance(history_unfiltered, list)
                assert [row["event_id"] for row in history_filtered] == [
                    older_event_id,
                    latest_event_id,
                ]
        finally:
            transaction.rollback()
    engine.dispose()
