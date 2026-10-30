"""Transactional, idempotent persistence of telemetry events.

Every outcome is decided inside one PostgreSQL transaction and returned only after
it commits, so callers can publish the application ACK or rejection safely. A
database error propagates and no outcome is produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from evolver.db.models import (
    AuditEvent,
    Equipment,
    ExperimentRun,
    Measurement,
    Position,
    ProcessedEvent,
)
from evolver.ingestion.validation import AcceptedTelemetry, RejectedTelemetry, RejectionReason
from evolver_contracts import TelemetryEvent

QUARANTINE_ACTION = "telemetry_quarantined"
QUARANTINE_ENTITY = "telemetry_event"
INGESTION_ACTOR = "evolver-ingestion"


@dataclass(frozen=True)
class Persisted:
    event_id: UUID


@dataclass(frozen=True)
class Duplicate:
    event_id: UUID


@dataclass(frozen=True)
class Quarantined:
    event_id: UUID
    reason_code: RejectionReason
    detail: str | None


type StoreOutcome = Persisted | Duplicate | Quarantined


class TelemetryStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def persist(self, accepted: AcceptedTelemetry, *, received_at: datetime) -> StoreOutcome:
        """Store a valid event, or quarantine it when its source is not registered."""
        event = accepted.event
        with self._session_factory.begin() as session:
            position_id, rejection = _resolve_source(session, event)
            if rejection is not None:
                return _quarantine(
                    session,
                    RejectedTelemetry(
                        topic_equipment_id=accepted.topic_equipment_id,
                        event_id=event.event_id,
                        reason_code=rejection[0],
                        detail=rejection[1],
                        raw_payload=accepted.raw_payload,
                        event=event,
                    ),
                    received_at,
                )
            if not _claim_event_id(
                session,
                event_id=event.event_id,
                equipment_id=event.equipment_id,
                producer_id=event.producer_id,
                generated_at=event.generated_at,
                received_at=received_at,
                outcome="persisted",
            ):
                return _previous_outcome(session, event.event_id)
            session.add(
                Measurement(
                    event_id=event.event_id,
                    generated_at=event.generated_at,
                    received_at=received_at,
                    equipment_id=event.equipment_id,
                    position_id=position_id,
                    experiment_run_id=event.experiment_run_id,
                    producer_id=event.producer_id,
                    sequence=event.sequence,
                    measurement_type=event.measurement_type,
                    value=event.value,
                    schema_version=event.schema_version,
                )
            )
        return Persisted(event.event_id)

    def quarantine(self, rejected: RejectedTelemetry, *, received_at: datetime) -> StoreOutcome:
        """Reserve the event_id as quarantined so a resend gets the same answer."""
        with self._session_factory.begin() as session:
            return _quarantine(session, rejected, received_at)


def _resolve_source(
    session: Session, event: TelemetryEvent
) -> tuple[UUID | None, tuple[RejectionReason, str] | None]:
    equipment = session.get(Equipment, event.equipment_id)
    if equipment is None or not equipment.enabled:
        return None, ("unknown_equipment", f"equipamento {event.equipment_id} não cadastrado")

    position_id = session.scalar(
        select(Position.id).where(
            Position.equipment_id == event.equipment_id,
            Position.vial_id == event.vial_id,
            Position.enabled,
        )
    )
    if position_id is None:
        return None, (
            "unknown_vial",
            f"vial {event.vial_id} sem posição habilitada em {event.equipment_id}",
        )

    if event.experiment_run_id is not None:
        run = session.get(ExperimentRun, event.experiment_run_id)
        if run is None or run.position_id != position_id:
            # O contrato v1 não tem motivo próprio para execução desconhecida.
            return None, (
                "schema_invalid",
                f"experiment_run_id {event.experiment_run_id} não pertence ao vial "
                f"{event.vial_id}",
            )
    return position_id, None


def _claim_event_id(session: Session, **values: Any) -> bool:
    """Insert the ledger row; False means another delivery already owns the event_id."""
    claimed = session.execute(
        insert(ProcessedEvent)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[ProcessedEvent.event_id])
        .returning(ProcessedEvent.event_id)
    ).first()
    return claimed is not None


def _quarantine(
    session: Session, rejected: RejectedTelemetry, received_at: datetime
) -> StoreOutcome:
    event = rejected.event
    if not _claim_event_id(
        session,
        event_id=rejected.event_id,
        # O tópico é a origem autenticada pelo broker, mesmo quando o payload diverge.
        equipment_id=rejected.topic_equipment_id,
        producer_id=event.producer_id if event else None,
        generated_at=event.generated_at if event else None,
        received_at=received_at,
        outcome="quarantined",
    ):
        return _previous_outcome(session, rejected.event_id)
    session.add(
        AuditEvent(
            occurred_at=received_at,
            actor_id=INGESTION_ACTOR,
            action=QUARANTINE_ACTION,
            entity_type=QUARANTINE_ENTITY,
            entity_id=str(rejected.event_id),
            correlation_id=rejected.event_id,
            details={
                "reason_code": rejected.reason_code,
                "detail": rejected.detail,
                "equipment_id": rejected.topic_equipment_id,
                "payload": rejected.raw_payload,
            },
        )
    )
    return Quarantined(rejected.event_id, rejected.reason_code, rejected.detail)


def _previous_outcome(session: Session, event_id: UUID) -> StoreOutcome:
    """Answer a resend with the outcome recorded for its first delivery."""
    outcome = session.scalar(
        select(ProcessedEvent.outcome).where(ProcessedEvent.event_id == event_id)
    )
    if outcome == "persisted":
        return Duplicate(event_id)
    details = session.scalar(
        select(AuditEvent.details)
        .where(
            AuditEvent.entity_type == QUARANTINE_ENTITY,
            AuditEvent.entity_id == str(event_id),
            AuditEvent.action == QUARANTINE_ACTION,
        )
        .order_by(AuditEvent.occurred_at.desc())
        .limit(1)
    ) or {}
    return Quarantined(
        event_id,
        details.get("reason_code", "schema_invalid"),
        details.get("detail"),
    )
