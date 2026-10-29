"""SQLAlchemy mappings for the pilot's PostgreSQL and TimescaleDB schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base metadata used by Alembic and database tooling."""


class Equipment(Base):
    __tablename__ = "equipment"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(
        default=True, server_default=text("true"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint(
            "equipment_id", "position_code", name="uq_positions_equipment_code"
        ),
        UniqueConstraint("equipment_id", "id", name="uq_positions_equipment_id_id"),
        Index(
            "uq_positions_enabled_vial",
            "vial_id",
            unique=True,
            postgresql_where=text("enabled"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    equipment_id: Mapped[str] = mapped_column(ForeignKey("equipment.id", ondelete="RESTRICT"))
    position_code: Mapped[str] = mapped_column(String(64), nullable=False)
    vial_id: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        default=True, server_default=text("true"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Culture(Base):
    __tablename__ = "cultures"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    vial_id: Mapped[str] = mapped_column(String(64), nullable=False)
    organism: Mapped[str | None] = mapped_column(String(120))
    label: Mapped[str | None] = mapped_column(String(120))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["equipment_id", "position_id"],
            ["positions.equipment_id", "positions.id"],
            name="fk_experiment_runs_equipment_position",
            ondelete="RESTRICT",
        ),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ck_run_time_order"),
        Index("ix_experiment_runs_position_started", "position_id", text("started_at DESC")),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    equipment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    position_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    culture_id: Mapped[UUID | None] = mapped_column(ForeignKey("cultures.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )


class ProcessedEvent(Base):
    """Global idempotency ledger; insert this before the measurement in one transaction."""

    __tablename__ = "processed_event_ids"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "generated_at", name="uq_processed_event_ids_event_generated"
        ),
        CheckConstraint(
            "outcome IN ('persisted', 'quarantined')", name="ck_processed_event_outcome"
        ),
        CheckConstraint(
            "outcome = 'quarantined' OR (equipment_id IS NOT NULL AND "
            "producer_id IS NOT NULL AND generated_at IS NOT NULL)",
            name="ck_processed_event_persisted_fields",
        ),
        Index("ix_processed_event_ids_received_at", text("received_at DESC")),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    equipment_id: Mapped[str | None] = mapped_column(String(64))
    producer_id: Mapped[str | None] = mapped_column(String(64))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(
        String(16), default="persisted", server_default=text("'persisted'"), nullable=False
    )


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "generated_at"],
            ["processed_event_ids.event_id", "processed_event_ids.generated_at"],
            name="fk_measurements_processed_event",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["equipment_id", "position_id"],
            ["positions.equipment_id", "positions.id"],
            name="fk_measurements_equipment_position",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["experiment_run_id"], ["experiment_runs.id"], ondelete="SET NULL"
        ),
        PrimaryKeyConstraint("event_id", "generated_at", name="pk_measurements"),
        CheckConstraint("sequence >= 0", name="ck_measurement_sequence"),
        CheckConstraint(
            "measurement_type IN ('od', 'ph', 'temperature')", name="ck_measurement_type"
        ),
        Index("ix_measurements_equipment_time", "equipment_id", text("generated_at DESC")),
        Index("ix_measurements_position_time", "position_id", text("generated_at DESC")),
        Index("ix_measurements_type_time", "measurement_type", text("generated_at DESC")),
        Index(
            "ix_measurements_equipment_position_type_time",
            "equipment_id",
            "position_id",
            "measurement_type",
            text("generated_at DESC"),
        ),
        Index("ix_measurements_received_at", text("received_at DESC")),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    position_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    experiment_run_id: Mapped[str | None] = mapped_column(String(64))
    producer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    measurement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Float(precision=53), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)


class Command(Base):
    __tablename__ = "commands"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_command_expiry"),
        CheckConstraint(
            "status IN ('requested', 'accepted', 'rejected', 'sent', 'received', "
            "'executed', 'failed', 'unknown', 'expired')",
            name="ck_command_status",
        ),
        Index("ix_commands_equipment_created", "equipment_id", text("created_at DESC")),
        Index("ix_commands_status_expiry", "status", "expires_at"),
    )

    command_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    equipment_id: Mapped[str] = mapped_column(ForeignKey("equipment.id", ondelete="RESTRICT"))
    experiment_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("experiment_runs.id", ondelete="SET NULL")
    )
    author_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index(
            "ix_audit_entity_time",
            "entity_type",
            "entity_id",
            text("occurred_at DESC"),
        ),
        Index("ix_audit_actor_time", "actor_id", text("occurred_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    correlation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
