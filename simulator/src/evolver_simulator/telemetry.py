"""Geracao deterministica de eventos de OD simulada."""

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


class OdTelemetryGenerator:
    """Gera vials em ordem circular e valores de OD reproduziveis pela semente."""

    _CYCLE_LENGTH = 24
    _VIAL_OFFSET = 0.01

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
        vial_index = sequence % len(self._settings.vial_ids)
        vial_cycle = sequence // len(self._settings.vial_ids)
        phase = 2 * math.pi * (vial_cycle % self._CYCLE_LENGTH) / self._CYCLE_LENGTH
        noise = self._rng.uniform(-self._settings.od_noise, self._settings.od_noise)
        value = max(
            0.0,
            self._settings.od_baseline
            + vial_index * self._VIAL_OFFSET
            + self._settings.od_variation * math.sin(phase)
            + noise,
        )

        event = TelemetryEvent(
            schema_version="1.0",
            event_id=self._uuid_factory(),
            producer_id=self._settings.producer_id,
            equipment_id=self._settings.equipment_id,
            vial_id=self._settings.vial_ids[vial_index],
            measurement_type="od",
            value=round(value, 6),
            generated_at=self._clock(),
            sequence=sequence,
        )
        self._sequence += 1
        return event
