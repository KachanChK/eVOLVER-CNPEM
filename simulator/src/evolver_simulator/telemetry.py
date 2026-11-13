"""Geração das medições simuladas, sem acesso ao MQTT ou ao banco."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from evolver_contracts.models import TelemetryEvent
from evolver_contracts.pilot import ActiveVial

from .config import SimulatorSettings

Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]
MEASUREMENT_TYPES = ("od", "ph", "temperature")


def utc_now() -> datetime:
    return datetime.now(UTC)


class SimulatedTelemetryGenerator:
    """Gera OD, pH e temperatura em ordem para cada frasco."""

    _CYCLE_LENGTHS = {"od": 19, "ph": 29, "temperature": 37}

    def __init__(
        self,
        settings: SimulatorSettings,
        allocations: list[ActiveVial],
        *,
        rng: random.Random | None = None,
        clock: Clock = utc_now,
        uuid_factory: UuidFactory = uuid4,
    ) -> None:
        self._settings = settings
        self._allocations = allocations
        seed_source = rng if rng is not None else random.Random(settings.seed)
        self._generators = {
            kind: random.Random(seed_source.getrandbits(128)) for kind in MEASUREMENT_TYPES
        }
        self._phases = {
            kind: self._generators[kind].uniform(0, math.tau) for kind in MEASUREMENT_TYPES
        }
        self._clock = clock
        self._uuid_factory = uuid_factory
        self._sequence = 0

    def next_event(self) -> TelemetryEvent:
        sequence = self._sequence
        allocations = self._allocations
        types = MEASUREMENT_TYPES

        # Cada vial recebe os três tipos de medição em cada rodada.
        measurement_type = types[sequence % len(types)]
        vial_turn = sequence // len(types)
        vial_index = vial_turn % len(allocations)
        cycle = vial_turn // len(allocations)
        value = self._value_for(measurement_type, vial_index, cycle)

        event = TelemetryEvent(
            schema_version="1.0",
            event_id=self._uuid_factory(),
            producer_id=self._settings.producer_id,
            equipment_id=self._settings.equipment_id,
            vial_id=str(allocations[vial_index].vial_id),
            experiment_run_id=str(allocations[vial_index].experiment_id),
            measurement_type=measurement_type,
            value=value,
            generated_at=self._clock(),
            sequence=sequence,
        )
        self._sequence += 1
        return event

    def _value_for(self, measurement_type: str, vial_index: int, cycle: int) -> float:
        settings = self._settings
        # Cada conjunto contém: valor base, variação, ruído e diferença por frasco.
        profiles = {
            "od": (settings.od_baseline, settings.od_variation, settings.od_noise, 0.01),
            "ph": (settings.ph_baseline, settings.ph_variation, settings.ph_noise, 0.02),
            "temperature": (
                settings.temperature_baseline,
                settings.temperature_variation,
                settings.temperature_noise,
                0.1,
            ),
        }
        if measurement_type not in profiles:
            raise ValueError(f"unsupported simulated measurement type: {measurement_type}")
        baseline, variation, noise_amplitude, vial_offset = profiles[measurement_type]

        # Cada medição tem fase, período e ruído próprios; são apenas dados de teste.
        phase = (
            self._phases[measurement_type]
            + math.tau * cycle / self._CYCLE_LENGTHS[measurement_type]
        )
        noise = self._generators[measurement_type].uniform(-noise_amplitude, noise_amplitude)
        value = baseline + vial_index * vial_offset + variation * math.sin(phase) + noise
        if measurement_type == "od":
            value = max(0.0, value)
        return round(value, 6)
