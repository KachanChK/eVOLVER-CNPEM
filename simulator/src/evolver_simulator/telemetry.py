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
OD_RISE_PER_SAMPLE = 0.02
OD_FALL_PER_SAMPLE = 0.05


def utc_now() -> datetime:
    return datetime.now(UTC)


class SimulatedTelemetryGenerator:
    """Gera OD, pH e temperatura em ordem para cada frasco."""

    _CYCLE_LENGTHS = {"ph": 29, "temperature": 37}

    def __init__(
        self,
        settings: SimulatorSettings,
        allocations: list[ActiveVial],
        *,
        pump_is_on: Callable[[ActiveVial], bool] = lambda _allocation: False,
        rng: random.Random | None = None,
        clock: Clock = utc_now,
        uuid_factory: UuidFactory = uuid4,
    ) -> None:
        self._settings = settings
        self._allocations = allocations
        self._pump_is_on = pump_is_on
        self._od_states: dict[tuple[int, int, UUID | None], tuple[float, random.Random]] = {}
        seed_source = rng if rng is not None else random.Random(settings.seed)
        seeds = {kind: seed_source.getrandbits(128) for kind in MEASUREMENT_TYPES}
        self._od_seed = seeds["od"]
        self._generators = {
            kind: random.Random(seeds[kind]) for kind in self._CYCLE_LENGTHS
        }
        self._phases = {
            kind: generator.uniform(0, math.tau) for kind, generator in self._generators.items()
        }
        self._clock = clock
        self._uuid_factory = uuid_factory
        self._sequence = 0
        self._position = 0
        self._cycle = 0

    def update_allocations(self, allocations: list[ActiveVial]) -> None:
        """Atualiza os frascos entre rodadas, preservando a sequência e os geradores."""
        self._allocations = list(allocations)
        active = {(vial.vial_id, vial.experiment_id, vial.allocation_id) for vial in allocations}
        self._od_states = {key: state for key, state in self._od_states.items() if key in active}
        self._position = 0

    def next_event(self) -> TelemetryEvent:
        sequence = self._sequence
        allocations = self._allocations
        types = MEASUREMENT_TYPES
        if not allocations:
            raise ValueError("no active vials to simulate")

        # Cada vial recebe os três tipos de medição em cada rodada.
        measurement_type = types[self._position % len(types)]
        vial_index = self._position // len(types)
        allocation = allocations[vial_index]
        if measurement_type == "od":
            value = self._next_od(allocation)
        else:
            value = self._value_for(measurement_type, vial_index, self._cycle)

        event = TelemetryEvent(
            schema_version="1.0",
            event_id=self._uuid_factory(),
            producer_id=self._settings.producer_id,
            equipment_id=self._settings.equipment_id,
            vial_id=str(allocation.vial_id),
            experiment_run_id=str(allocation.experiment_id),
            measurement_type=measurement_type,
            value=value,
            generated_at=self._clock(),
            sequence=sequence,
        )
        self._sequence += 1
        self._position += 1
        if self._position == len(allocations) * len(types):
            self._position = 0
            self._cycle += 1
        return event

    def _next_od(self, allocation: ActiveVial) -> float:
        key = (allocation.vial_id, allocation.experiment_id, allocation.allocation_id)
        previous = self._od_states.get(key)
        if previous is None:
            value = round(self._settings.od_baseline, 6)
            rng = random.Random(f"{self._od_seed}:{key[0]}:{key[1]}")
        else:
            value, rng = previous
            step = -OD_FALL_PER_SAMPLE if self._pump_is_on(allocation) else OD_RISE_PER_SAMPLE
            noise = rng.uniform(-self._settings.od_noise, self._settings.od_noise)
            value = round(min(0.80, max(0.10, value + step + noise)), 6)
        self._od_states[key] = (value, rng)
        return value

    def _value_for(self, measurement_type: str, vial_index: int, cycle: int) -> float:
        settings = self._settings
        # Cada conjunto contém: valor base, variação, ruído e diferença por frasco.
        profiles = {
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
        return round(value, 6)
