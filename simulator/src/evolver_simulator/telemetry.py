"""Geracao deterministica de telemetria simulada."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from evolver_contracts.models import TelemetryEvent

from .config import SimulatorSettings

Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]


def utc_now() -> datetime:
    return datetime.now(UTC)


class SimulatedTelemetryGenerator:
    """Gera OD, pH e temperatura mockados e reproduziveis pela semente."""

    _CYCLE_LENGTH = 24
    _MEASUREMENT_TYPES = ("od", "ph", "temperature")

    def __init__(
        self,
        settings: SimulatorSettings,
        *,
        rng: random.Random | None = None,
        clock: Clock = utc_now,
        uuid_factory: UuidFactory = uuid4,
    ) -> None:
        self._settings = settings
        self._rng = rng if rng is not None else random.Random(settings.seed)
        self._clock = clock
        self._uuid_factory = uuid_factory
        self._sequence = 0

    def next_event(self) -> TelemetryEvent:
        sequence = self._sequence
        measurement_count = len(self._MEASUREMENT_TYPES)
        measurement_type = self._MEASUREMENT_TYPES[sequence % measurement_count]
        vial_index = (sequence // measurement_count) % len(self._settings.vial_ids)
        vial_cycle = sequence // (measurement_count * len(self._settings.vial_ids))
        phase = 2 * math.pi * (vial_cycle % self._CYCLE_LENGTH) / self._CYCLE_LENGTH
        value = self._value_for(measurement_type, vial_index, phase)

        event = TelemetryEvent(
            schema_version="1.0",
            event_id=self._uuid_factory(),
            producer_id=self._settings.producer_id,
            equipment_id=self._settings.equipment_id,
            vial_id=self._settings.vial_ids[vial_index],
            measurement_type=measurement_type,
            value=value,
            generated_at=self._clock(),
            sequence=sequence,
        )
        self._sequence += 1
        return event

    def _value_for(self, measurement_type: str, vial_index: int, phase: float) -> float:
        if measurement_type == "od":
            baseline = self._settings.od_baseline
            variation = self._settings.od_variation
            noise_amplitude = self._settings.od_noise
            vial_offset = 0.01
        elif measurement_type == "ph":
            baseline = self._settings.ph_baseline
            variation = self._settings.ph_variation
            noise_amplitude = self._settings.ph_noise
            vial_offset = 0.02
        elif measurement_type == "temperature":
            baseline = self._settings.temperature_baseline
            variation = self._settings.temperature_variation
            noise_amplitude = self._settings.temperature_noise
            vial_offset = 0.1
        else:
            raise ValueError(f"unsupported simulated measurement type: {measurement_type}")

        noise = self._rng.uniform(-noise_amplitude, noise_amplitude)
        value = baseline + vial_index * vial_offset + variation * math.sin(phase) + noise
        if measurement_type == "od":
            value = max(0.0, value)
        return round(value, 6)
