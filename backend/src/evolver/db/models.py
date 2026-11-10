"""The minimal schema for temperature readings from simulated vials."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    PrimaryKeyConstraint,
    String,
    Uuid,
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


class TemperatureReading(Base):
    __tablename__ = "temperature_readings"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", "generated_at"),
        Index("ix_temperature_readings_vial_time", "vial_id", "generated_at"),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    vial_id: Mapped[int] = mapped_column(
        ForeignKey("vials.vial_id", ondelete="RESTRICT"), nullable=False
    )
    temperature_celsius: Mapped[float] = mapped_column(Float(precision=53), nullable=False)

    vial: Mapped[Vial] = relationship()
