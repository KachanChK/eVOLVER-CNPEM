"""Ciclo de vida do produtor periodico."""

from __future__ import annotations

import logging
import threading

from .config import SimulatorSettings
from .mqtt import MqttPublisher
from .telemetry import SimulatedTelemetryGenerator

LOGGER = logging.getLogger(__name__)


class SimulatedFailureError(RuntimeError):
    """Falha deterministica solicitada pela configuracao do simulador."""


class SimulatorRunner:
    """Conecta, publica periodicamente e encerra liberando o cliente MQTT."""

    def __init__(
        self,
        settings: SimulatorSettings,
        *,
        generator: SimulatedTelemetryGenerator | None = None,
        publisher: MqttPublisher | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._settings = settings
        self._generator = generator or SimulatedTelemetryGenerator(settings)
        self._publisher = publisher or MqttPublisher(settings)
        self._stop_event = stop_event or threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self, *, max_messages: int | None = None) -> int:
        limit = max_messages if max_messages is not None else self._settings.max_messages
        published = 0
        try:
            self._publisher.connect()
            while not self._stop_event.is_set() and (limit is None or published < limit):
                self._publisher.publish(self._generator.next_event())
                published += 1

                if self._settings.fail_after_messages == published:
                    raise SimulatedFailureError(
                        f"simulated failure after {published} published messages",
                    )
                if limit is not None and published >= limit:
                    break

                wait_seconds = self._settings.interval_seconds
                is_simulated_pause = self._settings.pause_after_messages == published
                if is_simulated_pause:
                    wait_seconds = self._settings.pause_seconds
                    LOGGER.warning(
                        "Pausa simulada de %s segundo(s) apos %s mensagem(ns)",
                        wait_seconds,
                        published,
                    )
                if self._stop_event.wait(wait_seconds):
                    break
                if is_simulated_pause:
                    LOGGER.info("Pausa simulada concluida; retomando publicacoes")
        finally:
            self._publisher.close()

        LOGGER.info("Produtor encerrado apos %s mensagem(ns)", published)
        return published
