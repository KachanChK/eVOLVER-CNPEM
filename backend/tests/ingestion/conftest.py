from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from evolver.db.models import Position
from evolver.db.seed import seed_simulated_equipment
from evolver.ingestion.persistence import TelemetryStore

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.getenv("EVOLVER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set EVOLVER_TEST_DATABASE_URL to a disposable TimescaleDB database")
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    # O env.py do Alembic prioriza DATABASE_URL; nunca migrar o banco de desenvolvimento.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", url)
        command.upgrade(config, "head")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)


@pytest.fixture
def store(session_factory: sessionmaker[Session]) -> TelemetryStore:
    return TelemetryStore(session_factory)


@dataclass(frozen=True)
class Source:
    equipment_id: str
    vial_id: str


def register_source(
    session_factory: sessionmaker[Session], equipment_id: str | None = None
) -> Source:
    """Each test gets its own vial, since an enabled vial is unique across positions."""
    source = Source(equipment_id or f"test-{uuid4().hex[:12]}", f"vial-{uuid4().hex[:12]}")
    with session_factory.begin() as session:
        seed_simulated_equipment(session, equipment_id=source.equipment_id, vial_ids=[])
        session.add(
            Position(
                id=uuid4(),
                equipment_id=source.equipment_id,
                position_code=source.vial_id,
                vial_id=source.vial_id,
                created_at=datetime.now(UTC),
            )
        )
    return source


@pytest.fixture
def source(session_factory: sessionmaker[Session]) -> Source:
    return register_source(session_factory)
