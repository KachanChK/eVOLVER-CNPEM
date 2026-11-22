"""The minimal schema for temperature readings from simulated vials."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

OD_MIN = Decimal("0.10")
OD_MAX = Decimal("0.80")


class Base(DeclarativeBase):
    pass


class Vial(Base):
    __tablename__ = "vials"

    vial_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    equipment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint("ended_at >= started_at", name="ck_experiment_interval"),
        CheckConstraint(
            "deleted_at IS NULL OR (ended_at IS NOT NULL AND deleted_at >= ended_at)",
            name="ck_experiment_deletion",
        ),
        CheckConstraint(
            "(od_min IS NULL AND od_max IS NULL) OR "
            "(od_min IS NOT NULL AND od_max IS NOT NULL "
            "AND od_min >= 0.10 AND od_max <= 0.80 AND od_min < od_max)",
            name="ck_experiment_od_limits",
        ),
        Index(
            "uq_experiments_active_vial",
            "vial_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    culture_type: Mapped[str | None] = mapped_column(Text)
    od_min: Mapped[Decimal | None] = mapped_column(Numeric)
    od_max: Mapped[Decimal | None] = mapped_column(Numeric)
    vial_id: Mapped[int] = mapped_column(ForeignKey("vials.vial_id", ondelete="RESTRICT"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def status(self) -> str:
        return "active" if self.ended_at is None else "inactive"

    @property
    def eligible_for_od_control(self) -> bool:
        return (
            self.ended_at is None
            and self.deleted_at is None
            and self.od_min is not None
            and self.od_max is not None
            and OD_MIN <= self.od_min < self.od_max <= OD_MAX
        )


class TemperatureReading(Base):
    __tablename__ = "temperature_readings"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", "generated_at"),
        Index("ix_temperature_readings_vial_time", "vial_id", "generated_at"),
        Index("ix_temperature_readings_experiment_time", "experiment_id", "generated_at"),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    vial_id: Mapped[int] = mapped_column(
        ForeignKey("vials.vial_id", ondelete="RESTRICT"), nullable=False
    )
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("experiments.id", ondelete="RESTRICT"), nullable=False
    )
    temperature_celsius: Mapped[float] = mapped_column(Float(precision=53), nullable=False)

    vial: Mapped[Vial] = relationship()


class PhReading(Base):
    __tablename__ = "ph_readings"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", "generated_at"),
        Index("ix_ph_readings_vial_time", "vial_id", "generated_at"),
        Index("ix_ph_readings_experiment_time", "experiment_id", "generated_at"),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    vial_id: Mapped[int] = mapped_column(ForeignKey("vials.vial_id", ondelete="RESTRICT"))
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="RESTRICT"))
    ph_value: Mapped[float] = mapped_column(Float(precision=53), nullable=False)

    @property
    def value(self) -> float:
        return self.ph_value


class OdReading(Base):
    __tablename__ = "od_readings"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", "generated_at"),
        Index("ix_od_readings_vial_time", "vial_id", "generated_at"),
        Index("ix_od_readings_experiment_time", "experiment_id", "generated_at"),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    vial_id: Mapped[int] = mapped_column(ForeignKey("vials.vial_id", ondelete="RESTRICT"))
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="RESTRICT"))
    od_value: Mapped[float] = mapped_column(Float(precision=53), nullable=False)
    producer_id: Mapped[str | None] = mapped_column(String(64))
    sequence: Mapped[int | None] = mapped_column(BigInteger)

    @property
    def value(self) -> float:
        return self.od_value


class PumpControl(Base):
    __tablename__ = "pump_control"

    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), primary_key=True)
    vial_id: Mapped[int] = mapped_column(ForeignKey("vials.vial_id"), nullable=False)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delete_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reconcile_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_state: Mapped[str] = mapped_column(String(16), nullable=False)
    desired_state: Mapped[str] = mapped_column(String(16), nullable=False)
    last_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_producer_id: Mapped[str | None] = mapped_column(String(64))
    last_sequence: Mapped[int | None] = mapped_column(BigInteger)
    pending_command_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))


class PumpCommandRecord(Base):
    __tablename__ = "pump_commands"

    command_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), nullable=False)
    vial_id: Mapped[int] = mapped_column(ForeignKey("vials.vial_id"), nullable=False)
    reading_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reading_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    desired_state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    puback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_detail: Mapped[str | None] = mapped_column(Text)
