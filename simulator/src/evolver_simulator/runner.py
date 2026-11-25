"""Coleta periódica independente da sessão e da entrega da telemetria."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

from evolver_contracts.models import TelemetryEvent, TelemetryRejection
from evolver_contracts.pilot import ActiveVial
from paho.mqtt.client import MQTTMessageInfo
from pydantic import ValidationError

from .config import SimulatorSettings
from .mqtt import (
    AllocationQuery,
    MqttConnectionError,
    MqttPublisher,
    MqttPublishError,
    PumpStateError,
)
from .queue import TelemetryQueue
from .scenarios import Scenarios
from .telemetry import MEASUREMENT_TYPES, SimulatedTelemetryGenerator

LOGGER = logging.getLogger(__name__)
ROUND_INTERVAL_SECONDS = 0.5
TICK_SECONDS = 0.025
ACK_TIMEOUT = 5.0
LIVE_WINDOW = 2.0
WINDOW = 128
HISTORY_WINDOW = 12 * len(MEASUREMENT_TYPES)


class SimulatedFailureError(RuntimeError):
    """Falha determinística solicitada pela configuração do simulador."""


@dataclass
class Attempt:
    number: int
    sent_at: float
    live: bool
    info: MQTTMessageInfo | None


class Delivery:
    def __init__(self, queue: TelemetryQueue, publisher: MqttPublisher, clock: Callable[[], float]):
        self.queue = queue
        self.publisher = publisher
        self.clock = clock
        self.waiting: dict[int, Attempt] = {}
        self.session: int | None = None
        self.confirmed = 0
        self.historical = 0
        self.degraded: str | None = None

    @staticmethod
    def backoff(attempt: int) -> int:
        return min(30, 2 ** min(attempt - 1, 5))

    def retry(self, row_id: int, now: float) -> None:
        attempt = self.waiting[row_id]
        self.queue.schedule(row_id, attempt.number, now + self.backoff(attempt.number))
        del self.waiting[row_id]

    def receive(self) -> None:
        for row_id, response in self.queue.apply(list(self.publisher.outcomes())):
            attempt = self.waiting.pop(row_id, None)
            if isinstance(response, TelemetryRejection):
                LOGGER.warning(
                    "Telemetria em quarentena event_id=%s código=%s detalhe=%s",
                    response.event_id, response.reason_code, response.detail,
                )
            else:
                self.confirmed += 1
                self.historical += int(attempt is None or not attempt.live)

    def step(self, now: float, session: int | None) -> None:
        self.receive()
        if session != self.session:
            for row_id in list(self.waiting):
                self.retry(row_id, now)
            self.session = session
            state = "aguardando MQTT" if session is None else "disponível após SUBACK"
            LOGGER.info("Envio %s", state)
        if session is None:
            return
        for row_id, attempt in list(self.waiting.items()):
            if attempt.info is not None:
                reason = self.publisher.publish_outcome(attempt.info, session)
                if reason is not None:
                    if reason.is_failure:
                        self.retry(row_id, now)
                        LOGGER.warning("PUBACK recusado para linha %s: %s", row_id, reason)
                        continue
                    attempt.info = None
                elif now - attempt.sent_at >= LIVE_WINDOW:
                    LOGGER.warning("Sessão MQTT encerrada após timeout de PUBACK")
                    self.publisher.disconnect()
                    return
            if now - attempt.sent_at >= ACK_TIMEOUT:
                self.retry(row_id, now)
        self.send(session, WINDOW - len(self.waiting), live=True)
        historical = sum(not attempt.live for attempt in self.waiting.values())
        # Leave room for live batches and discovery even when the outbox is backlogged.
        available = min(WINDOW - len(self.waiting), HISTORY_WINDOW - historical)
        self.send(session, available, live=False)

    def send(self, session: int, limit: int, *, live: bool) -> None:
        if limit <= 0:
            return
        for row in self.queue.eligible(self.clock(), session, limit, live=live):
            row_id = row["id"]
            try:
                self.queue.validate(row)
            except (ValidationError, ValueError, TypeError, OverflowError) as exc:
                with self.queue.database:
                    self.queue.quarantine(row_id, "schema_invalid", str(exc), datetime.now(UTC))
                LOGGER.warning("Registro inválido em quarentena linha=%s: %s", row_id, exc)
                continue
            now = self.clock()
            # A linha ao vivo que expirou durante o lote volta para a seleção histórica.
            if live and row["live_until"] <= now:
                continue
            number = row["attempts"] + 1
            self.queue.schedule(row_id, number, now + ACK_TIMEOUT + self.backoff(number))
            try:
                info = self.publisher.publish(row["payload"], session=session, live=live)
            except (MqttConnectionError, MqttPublishError) as exc:
                self.queue.schedule(row_id, number, now + self.backoff(number))
                LOGGER.warning("Telemetria sem transporte event_id=%s: %s", row["event_id"], exc)
                return
            self.waiting[row_id] = Attempt(number, now, live, info)

    def log(self) -> None:
        pending, quarantined, oldest = self.queue.stats()
        age = max(0, (datetime.now(UTC) - oldest).total_seconds()) if oldest is not None else 0
        LOGGER.info(
            "Fila de telemetria pendentes=%s idade_mais_antiga=%.1fs quarentena=%s "
            "confirmados=%s históricos=%s",
            pending, age, quarantined, self.confirmed, self.historical,
        )
        self.confirmed = self.historical = 0


class SimulatorRunner:
    def __init__(
        self,
        settings: SimulatorSettings,
        *,
        publisher: MqttPublisher | None = None,
        stop_event: threading.Event | None = None,
        clock: Callable[[], float] = monotonic,
        scenarios: Scenarios | None = None,
    ) -> None:
        self._settings = settings
        self._publisher = publisher or MqttPublisher(settings, scenarios=scenarios)
        self._stop_event = stop_event or threading.Event()
        self._clock = clock
        self._scenarios = scenarios

    def stop(self) -> None:
        self._stop_event.set()

    def run(self, *, max_messages: int | None = None) -> int:
        limit = max_messages if max_messages is not None else self._settings.max_messages
        try:
            with (
                closing(TelemetryQueue(self._settings)) as queue,
                ThreadPoolExecutor(1) as connector,
            ):
                return self._run(queue, connector, limit)
        finally:
            self._publisher.close()

    def _run(self, queue: TelemetryQueue, connector: ThreadPoolExecutor, limit: int | None) -> int:
        publisher = self._publisher
        scenarios = self._scenarios
        delivery = Delivery(queue, publisher, self._clock)
        try:
            cached = queue.last_allocation()
        except (ValidationError, TypeError) as exc:
            LOGGER.warning("Lista de alocações local inválida: %s", exc)
            cached = None
        allocations: list[ActiveVial] | None = cached.vials if cached is not None else None
        allocation_ids = [vial.allocation_id for vial in allocations or []]
        generator = SimulatedTelemetryGenerator(
            self._settings, allocations or [], pump_is_on=publisher.pump_is_on,
        )
        now = self._clock()
        next_round = now + ROUND_INTERVAL_SECONDS
        next_connect = next_discovery = next_log = now
        connection: Future | None = None
        query: AllocationQuery | None = None
        query_at = 0.0
        fresh_session = None
        fresh_until = 0.0
        collect_state = None
        staged: list[TelemetryEvent] = []
        written = 0
        drain_until = None
        pause_after = self._settings.pause_after_messages
        fail_after = self._settings.fail_after_messages
        try:
            while not self._stop_event.is_set():
                now = self._clock()
                if connection is not None and connection.done():
                    try:
                        connection.result()
                    except PumpStateError:
                        raise
                    except MqttConnectionError as exc:
                        LOGGER.warning("Envio aguardando MQTT: %s", exc)
                    connection = None
                    next_connect = now + 1
                session = publisher.session
                if session is None and connection is None and now >= next_connect:
                    connection = connector.submit(publisher.connect)
                if query is not None:
                    if query.session != session or now - query_at >= 1 or query.finished.is_set():
                        publisher.cancel_query(query)
                        response = query.response
                        if response is not None and query.session == session:
                            vials = response.vials
                            if (
                                len({vial.vial_id for vial in vials}) != len(vials)
                                or len({vial.allocation_id for vial in vials}) != len(vials)
                                or any(vial.allocation_id is None for vial in vials)
                            ):
                                LOGGER.warning("Alocações inválidas: %s", response.request_id)
                            else:
                                try:
                                    queue.confirm_allocation(response)
                                except sqlite3.Error as exc:
                                    LOGGER.warning("Lista de alocações não persistida: %s", exc)
                                else:
                                    next_ids = [vial.allocation_id for vial in vials]
                                    if next_ids != allocation_ids:
                                        vial_ids = [vial.vial_id for vial in vials]
                                        LOGGER.info("Vials confirmados: %s", vial_ids)
                                        generator.update_allocations(vials)
                                        allocation_ids = next_ids
                                    allocations = vials
                                    if now - query_at < 1:
                                        fresh_session, fresh_until = session, now + 1
                                        if scenarios and scenarios.update(response, fresh_until):
                                            queue.release_held()
                        query = None
                if (
                    session is not None and query is None and now >= next_discovery
                    and drain_until is None
                ):
                    next_discovery = now + ROUND_INTERVAL_SECONDS
                    try:
                        query = (
                            publisher.request_allocations(session, include_test_state=True)
                            if scenarios else publisher.request_allocations(session)
                        )
                        query_at = now
                    except (MqttConnectionError, MqttPublishError) as exc:
                        LOGGER.warning("Consulta de alocações indisponível: %s", exc)

                if drain_until is None and now >= next_round:
                    next_round = max(next_round + ROUND_INTERVAL_SECONDS, now)
                    fresh = session is not None and fresh_session == session and now < fresh_until
                    state = (
                        "aguardando alocações" if allocations is None else
                        "sem vials ativos" if not allocations else
                        "com alocações confirmadas" if fresh else "com alocações locais"
                    )
                    size = len(allocations or []) * len(MEASUREMENT_TYPES)
                    for cutoff in (limit, fail_after, pause_after):
                        if cutoff is not None and cutoff > written:
                            size = min(size, cutoff - written)
                    size = len(staged) or size
                    try:
                        if size and not queue.has_room(size):
                            state = f"pausada: cota da fila insuficiente para {size} leituras"
                        elif size:
                            live_session = session if fresh and not staged else None
                            if not staged:
                                staged = [generator.next_event() for _ in range(size)]
                            events, scenario = (staged, None)
                            hold = scenarios.hold(ROUND_INTERVAL_SECONDS) if scenarios else None
                            if scenarios and live_session is not None:
                                events, scenario = scenarios.adjust(staged)
                            if queue.append(
                                events, session=live_session, live_until=now + LIVE_WINDOW,
                                hold=hold,
                            ):
                                if scenarios and scenario:
                                    scenarios.reading_written(scenario)
                                written += size
                                staged = []
                            else:
                                state = f"pausada: cota da fila insuficiente para {size} leituras"
                    except sqlite3.Error as exc:
                        state = f"pausada: falha de escrita no SQLite ({exc})"
                    if state != collect_state:
                        LOGGER.info("Coleta %s", state)
                        collect_state = state
                    if written == fail_after:
                        raise SimulatedFailureError(f"falha após {written} leituras gravadas")
                    if written == pause_after and pause_after is not None:
                        LOGGER.warning("Pausa simulada após %s leituras gravadas", written)
                        next_round = now + self._settings.pause_seconds
                        pause_after = None
                    if limit is not None and written >= limit:
                        drain_until = now + ACK_TIMEOUT

                try:
                    delivery.step(now, session)
                    if delivery.degraded is not None:
                        LOGGER.info("Envio recuperado após falha no SQLite")
                        delivery.degraded = None
                    if drain_until is not None and (now >= drain_until or not queue.has_pending()):
                        break
                    if now >= next_log:
                        delivery.log()
                        next_log = now + 5
                except sqlite3.Error as exc:
                    if str(exc) != delivery.degraded:
                        delivery.degraded = str(exc)
                        LOGGER.warning("Envio degradado por falha no SQLite: %s", exc)
                    if drain_until is not None and now >= drain_until:
                        break
                self._stop_event.wait(TICK_SECONDS)
        finally:
            try:
                delivery.log()
            except (sqlite3.Error, ValueError) as exc:
                LOGGER.warning("Não foi possível inspecionar a fila ao encerrar: %s", exc)
            LOGGER.info("Coleta encerrada após %s leituras novas gravadas", written)
        return written
