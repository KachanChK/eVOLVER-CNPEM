"""Ciclo de vida do produtor periodico."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from time import monotonic

from .config import SimulatorSettings
from .mqtt import MqttPublisher
from .telemetry import MEASUREMENT_TYPES, SimulatedTelemetryGenerator

LOGGER = logging.getLogger(__name__)
ROUNDS = 10
ROUND_INTERVAL_SECONDS = 0.5


class SimulatedFailureError(RuntimeError):
    """Falha deterministica solicitada pela configuracao do simulador."""


class SimulatorRunner:
    """Conecta, publica periodicamente e encerra liberando o cliente MQTT."""

    def __init__(
        self,
        settings: SimulatorSettings,
        *,
        publisher: MqttPublisher | None = None,
        stop_event: threading.Event | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._settings = settings
        self._publisher = publisher or MqttPublisher(settings)
        self._stop_event = stop_event or threading.Event()
        self._clock = clock

    def stop(self) -> None:
        self._stop_event.set()

    def run(self, *, max_messages: int | None = None) -> int:
        published = 0
        try:
            self._publisher.connect()
            allocations = self._publisher.active_vials()
            if not allocations:
                LOGGER.info("Nenhum vial ativo; nenhuma medicao enviada")
                return 0
            LOGGER.info(
                "Simulando os vials ativos: %s", ",".join(str(a.vial_id) for a in allocations)
            )
            generator = SimulatedTelemetryGenerator(self._settings, allocations)
            limit = ROUNDS * len(MEASUREMENT_TYPES) * len(allocations)
            requested_limit = (
                max_messages if max_messages is not None else self._settings.max_messages
            )
            if requested_limit is not None:
                limit = min(limit, requested_limit)
            started = self._clock()
            for round_number in range(1, ROUNDS + 1):
                deadline = started + round_number * ROUND_INTERVAL_SECONDS
                if self._stop_event.wait(max(0.0, deadline - self._clock())):
                    break
                for _ in range(len(allocations) * len(MEASUREMENT_TYPES)):
                    if self._stop_event.is_set() or published >= limit:
                        break
                    self._publisher.publish(generator.next_event())
                    published += 1
                    if self._settings.fail_after_messages == published:
                        raise SimulatedFailureError(
                            f"simulated failure after {published} published messages"
                        )
                    if self._settings.pause_after_messages == published:
                        LOGGER.warning("Pausa simulada apos %s mensagens", published)
                        if self._stop_event.wait(self._settings.pause_seconds):
                            break
                if published >= limit or self._stop_event.is_set():
                    break
        finally:
            self._publisher.close()

        LOGGER.info("Produtor encerrado apos %s mensagem(ns)", published)
        return published
