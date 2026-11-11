"""The minimal schema for temperature readings from simulated vials."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    PrimaryKeyConstraint,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
        Index(
            "uq_experiments_active_vial",
            "vial_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vial_id: Mapped[int] = mapped_column(ForeignKey("vials.vial_id", ondelete="RESTRICT"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def status(self) -> str:
        return "active" if self.ended_at is None else "inactive"


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
