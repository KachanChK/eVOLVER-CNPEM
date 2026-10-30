"""Ciclo de vida do produtor periodico."""

from __future__ import annotations

import logging
import threading

from .config import SimulatorSettings
from .mqtt import MqttPublisher
from .telemetry import OdTelemetryGenerator

LOGGER = logging.getLogger(__name__)


class SimulatorRunner:
    """Conecta, publica periodicamente e encerra liberando o cliente MQTT."""

    def __init__(
        self,
        settings: SimulatorSettings,
        *,
        generator: OdTelemetryGenerator | None = None,
        publisher: MqttPublisher | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._settings = settings
        self._generator = generator or OdTelemetryGenerator(settings)
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
                if limit is not None and published >= limit:
                    break
                if self._stop_event.wait(self._settings.interval_seconds):
                    break
        finally:
            self._publisher.close()

        LOGGER.info("Produtor encerrado apos %s mensagem(ns)", published)
        return published
