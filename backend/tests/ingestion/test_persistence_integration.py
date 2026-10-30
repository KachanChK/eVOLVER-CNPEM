from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from evolver.db.models import AuditEvent, ExperimentRun, Measurement, Position, ProcessedEvent
from evolver.db.queries import get_current_measurements, get_measurement_history
from evolver.ingestion.persistence import Duplicate, Persisted, Quarantined, TelemetryStore
from evolver.ingestion.validation import (
    AcceptedTelemetry,
    RejectedTelemetry,
    validate_telemetry,
)

from .conftest import Source
from .payloads import encode, telemetry

pytestmark = pytest.mark.integration


def validated(source: Source, **overrides: Any) -> AcceptedTelemetry | RejectedTelemetry:
    defaults = {
        "equipment_id": source.equipment_id,
        "vial_id": source.vial_id,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    payload = telemetry(**(defaults | overrides))
    return validate_telemetry(
        f"evolver/v1/{source.equipment_id}/telemetry",
        encode(payload),
        now=datetime.now(UTC),
        max_clock_skew=timedelta(minutes=5),
    )


def measurement_count(session_factory: sessionmaker[Session], event_id: UUID) -> int:
    with session_factory() as session:
        return session.scalar(
            select(func.count()).select_from(Measurement).where(Measurement.event_id == event_id)
        )


def ledger_outcome(session_factory: sessionmaker[Session], event_id: UUID) -> str | None:
    with session_factory() as session:
        return session.scalar(
            select(ProcessedEvent.outcome).where(ProcessedEvent.event_id == event_id)
        )


def test_event_is_persisted_once_and_resend_is_duplicate(
    store: TelemetryStore, session_factory: sessionmaker[Session], source: Source
) -> None:
    accepted = validated(source)
    received_at = datetime.now(UTC)

    first = store.persist(accepted, received_at=received_at)
    second = store.persist(accepted, received_at=received_at + timedelta(seconds=30))

    event_id = accepted.event.event_id
    assert first == Persisted(event_id)
    assert second == Duplicate(event_id)
    assert measurement_count(session_factory, event_id) == 1
    assert ledger_outcome(session_factory, event_id) == "persisted"
    with session_factory() as session:
        stored = session.scalar(select(Measurement).where(Measurement.event_id == event_id))
        assert stored.generated_at == accepted.event.generated_at
        assert stored.received_at == received_at
        assert stored.measurement_type == "od"


def test_commit_failure_leaves_nothing_and_resend_is_persisted(
    engine, session_factory: sessionmaker[Session], source: Source
) -> None:
    failing_factory = sessionmaker(engine)

    def fail_commit(session: Session) -> None:
        raise OperationalError("COMMIT", {}, Exception("simulated commit failure"))

    event.listen(failing_factory, "before_commit", fail_commit)
    accepted = validated(source)

    with pytest.raises(OperationalError):
        TelemetryStore(failing_factory).persist(accepted, received_at=datetime.now(UTC))

    event_id = accepted.event.event_id
    assert ledger_outcome(session_factory, event_id) is None
    assert measurement_count(session_factory, event_id) == 0
    # O reenvio do produtor grava normalmente; não é tratado como duplicata.
    assert TelemetryStore(session_factory).persist(
        accepted, received_at=datetime.now(UTC)
    ) == Persisted(event_id)


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"vial_id": "vial-not-registered"}, "unknown_vial"),
        ({"experiment_run_id": "run-not-registered"}, "schema_invalid"),
    ],
)
def test_unregistered_source_is_quarantined(
    store: TelemetryStore,
    session_factory: sessionmaker[Session],
    source: Source,
    overrides: dict,
    reason_code: str,
) -> None:
    accepted = validated(source, **overrides)

    outcome = store.persist(accepted, received_at=datetime.now(UTC))
    resent = store.persist(accepted, received_at=datetime.now(UTC))

    event_id = accepted.event.event_id
    assert isinstance(outcome, Quarantined)
    assert outcome.reason_code == reason_code
    assert resent == outcome
    assert ledger_outcome(session_factory, event_id) == "quarantined"
    assert measurement_count(session_factory, event_id) == 0


def test_unknown_equipment_is_quarantined_with_payload(
    store: TelemetryStore, session_factory: sessionmaker[Session]
) -> None:
    unknown = Source(f"test-{uuid4().hex[:12]}", "vial-01")
    accepted = validated(unknown)

    outcome = store.persist(accepted, received_at=datetime.now(UTC))

    assert isinstance(outcome, Quarantined)
    assert outcome.reason_code == "unknown_equipment"
    with session_factory() as session:
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.entity_id == str(accepted.event.event_id))
        )
        assert audit.action == "telemetry_quarantined"
        assert audit.details["reason_code"] == "unknown_equipment"
        assert audit.details["payload"] == accepted.raw_payload


def test_run_of_the_same_vial_is_linked(
    store: TelemetryStore, session_factory: sessionmaker[Session], source: Source
) -> None:
    run_id = f"run-{uuid4().hex[:12]}"
    with session_factory.begin() as session:
        position_id = session.scalar(select(Position.id).where(Position.vial_id == source.vial_id))
        session.add(
            ExperimentRun(
                id=run_id,
                equipment_id=source.equipment_id,
                position_id=position_id,
                started_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
    accepted = validated(source, experiment_run_id=run_id)

    assert store.persist(accepted, received_at=datetime.now(UTC)) == Persisted(
        accepted.event.event_id
    )


def test_schema_invalid_event_is_quarantined_and_resend_gets_same_answer(
    store: TelemetryStore, session_factory: sessionmaker[Session], source: Source
) -> None:
    rejected = validated(source, measurement_type=...)
    assert isinstance(rejected, RejectedTelemetry)

    first = store.quarantine(rejected, received_at=datetime.now(UTC))
    second = store.quarantine(rejected, received_at=datetime.now(UTC))

    assert first == second == Quarantined(rejected.event_id, "schema_invalid", rejected.detail)
    with session_factory() as session:
        ledger = session.get(ProcessedEvent, rejected.event_id)
        assert ledger.outcome == "quarantined"
        assert ledger.equipment_id == source.equipment_id
        assert ledger.generated_at is None


def test_resend_after_vial_transfer_is_still_duplicate(
    store: TelemetryStore, session_factory: sessionmaker[Session], source: Source
) -> None:
    accepted = validated(source)
    store.persist(accepted, received_at=datetime.now(UTC))
    with session_factory.begin() as session:
        session.execute(
            update(Position).where(Position.vial_id == source.vial_id).values(enabled=False)
        )

    assert store.persist(accepted, received_at=datetime.now(UTC)) == Duplicate(
        accepted.event.event_id
    )


def test_late_event_enters_history_without_replacing_current_reading(
    store: TelemetryStore, session_factory: sessionmaker[Session], source: Source
) -> None:
    now = datetime.now(UTC)
    latest = validated(source, generated_at=now.isoformat(), sequence=2, value=0.5)
    late = validated(
        source, generated_at=(now - timedelta(minutes=10)).isoformat(), sequence=1, value=0.2
    )

    store.persist(latest, received_at=now)
    store.persist(late, received_at=now + timedelta(seconds=5))

    with session_factory() as session:
        current = get_current_measurements(
            session, equipment_id=source.equipment_id, measurement_type="od"
        )
        history = get_measurement_history(
            session, equipment_id=source.equipment_id, measurement_type="od"
        )
    assert [row["event_id"] for row in current] == [latest.event.event_id]
    assert [row["event_id"] for row in history] == [late.event.event_id, latest.event.event_id]
    assert history[0]["received_at"] > history[1]["received_at"]
