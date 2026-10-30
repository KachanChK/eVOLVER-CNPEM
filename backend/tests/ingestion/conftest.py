from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from evolver.db.seed import seed_simulated_equipment
from evolver.ingestion.persistence import TelemetryStore


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
        result = seed_simulated_equipment(
            session, equipment_id=source.equipment_id, vial_ids=[source.vial_id]
        )
    assert source.vial_id in result.added
    return source


@pytest.fixture
def source(session_factory: sessionmaker[Session]) -> Source:
    return register_source(session_factory)
