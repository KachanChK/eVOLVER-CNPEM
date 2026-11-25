"""Temporary changes applied by the simulator's test center."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from threading import Lock
from time import monotonic

from evolver_contracts.models import TelemetryEvent
from evolver_contracts.pilot import AllocationResponse

SCENARIO_LABELS = {
    "temperature": "Pico de temperatura",
    "ph": "pH fora da faixa",
    "od": "OD fora da faixa",
    "pause": "Interromper envio de dados",
    "pump": "Falha nas bombas",
}
TEST_VALUES = {"temperature": 40.0, "ph": 7.70, "od": 0.85}


@dataclass
class Scenario:
    kind: str
    allocation_id: str
    until: float
    value: float | None
    applied: bool = False


class Scenarios:
    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._lock = Lock()
        self._response: AllocationResponse | None = None
        self._fresh_until = 0.0
        self._active: Scenario | None = None
        self._message = "Aguardando alocações ativas…"

    def update(self, response: AllocationResponse, fresh_until: float) -> bool:
        with self._lock:
            self._response = response
            self._fresh_until = fresh_until
            if self._active and not any(
                str(vial.allocation_id) == self._active.allocation_id for vial in response.vials
            ):
                release = self._active.kind == "pause"
                self._active = None
                self._message = "Teste encerrado. A alocação selecionada terminou."
                return release
            return False

    def start(self, kind: str, allocation_id: str) -> None:
        with self._lock:
            now = self._clock()
            if self._current(now):
                return
            response = self._response
            if response is None or now >= self._fresh_until:
                self._message = "Aguarde a confirmação das alocações pelo MQTT."
                return
            vial = next(
                (item for item in response.vials if str(item.allocation_id) == allocation_id), None,
            )
            if vial is None:
                self._message = "Selecione um experimento e vial ativos."
                return
            value = TEST_VALUES.get(kind)
            if kind == "pump":
                pump = vial.pump_test
                if pump is None or not pump.automatic or pump.confirmed_state == "unknown":
                    self._message = "O teste requer automação habilitada e estado confirmado."
                    return
                if (
                    pump.od_min is None or pump.od_max is None or pump.od_min >= pump.od_max
                    or response.od_alert_range is None
                ):
                    self._message = "O teste requer os limites de controle e alerta de OD."
                    return
                if not pump.pending:
                    on = pump.confirmed_state == "on"
                    limit = pump.od_min if on else pump.od_max
                    value = float(limit)
                    if (on and Decimal(str(value)) > limit) or (
                        not on and Decimal(str(value)) < limit
                    ):
                        value = math.nextafter(value, -math.inf if on else math.inf)
                    low, high = response.od_alert_range
                    if not low <= value <= high:
                        self._message = "O limite de controle está fora da faixa de alerta de OD."
                        return
            self._active = Scenario(
                kind, allocation_id, now + {"pump": 60, "pause": 20}.get(kind, 10), value,
            )

    def _current(self, now: float) -> Scenario | None:
        scenario = self._active
        if scenario is None or now < scenario.until:
            return scenario
        self._active = None
        if scenario.kind == "pause":
            self._message = "Envio retomado. A fila será enviada como histórico."
        elif scenario.kind == "pump" and scenario.applied:
            self._message = "Falha simulada encerrada. As bombas voltaram a receber comandos."
        else:
            self._message = "Tempo do teste encerrado sem leitura ou comando elegível."
        return None

    def snapshot(self):
        with self._lock:
            now = self._clock()
            scenario = self._current(now)
            vials = tuple(self._response.vials) if self._response is not None else ()
            if not scenario:
                message = self._message
                if message == "Aguardando alocações ativas…" and vials:
                    message = "Selecione um vial e um teste."
                return vials, False, message
            remaining = math.ceil(scenario.until - now)
            if scenario.kind == "pump":
                progress = "Falha aplicada" if scenario.applied else "Aguardando comando das bombas"
            elif scenario.kind == "pause":
                progress = "Envio interrompido para o vial selecionado"
            else:
                progress = "Aguardando a próxima leitura"
            return vials, True, f"{SCENARIO_LABELS[scenario.kind]} · {progress} ({remaining} s)"

    def hold(self, grace: float) -> tuple[str, float] | None:
        with self._lock:
            scenario = self._current(self._clock())
            if scenario and scenario.kind == "pause":
                return scenario.allocation_id, scenario.until + grace
            return None

    def adjust(self, events: list[TelemetryEvent]) -> tuple[list[TelemetryEvent], Scenario | None]:
        with self._lock:
            scenario = self._current(self._clock())
            if scenario is None or scenario.value is None:
                return events, None
            metric = "od" if scenario.kind == "pump" else scenario.kind
            for index, event in enumerate(events):
                if (
                    event.experiment_run_id == scenario.allocation_id
                    and event.measurement_type == metric
                ):
                    adjusted = list(events)
                    adjusted[index] = event.model_copy(update={"value": scenario.value})
                    return adjusted, scenario
            return events, None

    def reading_written(self, scenario: Scenario) -> None:
        with self._lock:
            if self._active is not scenario:
                return
            if scenario.kind == "pump":
                scenario.value = None
            else:
                self._active = None
                self._message = f"{SCENARIO_LABELS[scenario.kind]} · Leitura registrada para envio."

    def pump_failure(self, allocation_id: str) -> Scenario | None:
        with self._lock:
            scenario = self._current(self._clock())
            if scenario and scenario.kind == "pump" and scenario.allocation_id == allocation_id:
                return scenario
            return None

    def failure_written(self, scenario: Scenario) -> None:
        with self._lock:
            if self._active is scenario:
                scenario.applied = True
                scenario.value = None
