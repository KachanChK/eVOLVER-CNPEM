from contextlib import closing
from decimal import Decimal
from uuid import uuid4

import pytest
from evolver_contracts.pilot import ActiveVial, AllocationResponse, PumpTestState
from evolver_simulator.config import SimulatorSettings
from evolver_simulator.queue import TelemetryQueue
from evolver_simulator.scenarios import Scenarios
from evolver_simulator.telemetry import SimulatedTelemetryGenerator


@pytest.fixture
def sim(tmp_path):
    vials = [
        ActiveVial(vial_id=index, experiment_id=index, allocation_id=uuid4())
        for index in (1, 2)
    ]
    settings = SimulatorSettings(
        _env_file=None, mqtt_simulator_password="test",
        telemetry_queue_path=tmp_path / "readings.sqlite3", seed=4,
    )
    return settings, vials


@pytest.mark.parametrize("metric,value", [("temperature", 40), ("ph", 7.7), ("od", .85)])
def test_override_one_live_reading_preserves_generator_dynamics(sim, metric, value):
    settings, vials = sim
    scenarios = Scenarios(lambda: 0)
    scenarios.update(AllocationResponse(request_id=uuid4(), vials=vials), 1)
    scenarios.start(metric, str(vials[1].allocation_id))
    generator = SimulatedTelemetryGenerator(settings, vials)
    original = [generator.next_event() for _ in range(6)]
    changed, scenario = scenarios.adjust(original)
    index, = [i for i, (old, new) in enumerate(zip(original, changed, strict=True)) if old != new]
    assert changed[index].measurement_type == metric and changed[index].vial_id == "2"
    assert changed[index].value == value and changed[index].event_id == original[index].event_id
    scenarios.reading_written(scenario)
    reference = SimulatedTelemetryGenerator(settings, vials)
    assert [reference.next_event().value for _ in range(6)] == [event.value for event in original]
    following = [generator.next_event() for _ in range(6)]
    assert scenarios.adjust(following) == (following, None)
    assert [reference.next_event().value for _ in range(6)] == [event.value for event in following]


def test_pause_isolates_vial_and_keeps_original_events_for_history(sim):
    settings, vials = sim
    now = [0.0]
    scenarios = Scenarios(lambda: now[0])
    response = AllocationResponse(request_id=uuid4(), vials=vials)
    scenarios.update(response, 1)
    scenarios.start("pause", str(vials[0].allocation_id))
    scenarios.start("temperature", str(vials[1].allocation_id))
    generator = SimulatedTelemetryGenerator(settings, vials)
    readings = [generator.next_event() for _ in range(6)]
    with closing(TelemetryQueue(settings)) as queue:
        queue.append(readings, session=1, live_until=2, hold=scenarios.hold(.5))
        other_ids = [str(event.event_id) for event in readings[3:]]
        other = queue.eligible(0, 1, 6, live=True)
        assert [row["event_id"] for row in other] == other_ids
        assert [row["event_id"] for row in queue.eligible(19.9, 1, 6, live=False)] == other_ids
        now[0] = 20
        assert scenarios.hold(.5) is None
        queue.append([generator.next_event() for _ in range(6)], session=1, live_until=22)
        assert len(queue.eligible(20, 1, 6, live=True)) == 6
        historical = queue.eligible(20.5, 1, 6, live=False)
        assert [row["payload"] for row in historical[:3]] == [
            event.model_dump_json() for event in readings[:3]
        ]


def test_pump_checks_preconditions_and_ends_when_allocation_changes(sim):
    settings, vials = sim
    now = [0.0]
    scenarios = Scenarios(lambda: now[0])
    response = AllocationResponse(request_id=uuid4(), vials=vials, od_alert_range=(.1, .8))
    scenarios.update(response, 1)
    id_ = str(vials[0].allocation_id)
    scenarios.start("pump", id_)
    assert "automação habilitada" in scenarios.snapshot()[2]
    vials[0].pump_test = PumpTestState(
        automatic=True, confirmed_state="off", od_min=Decimal(".2"),
        od_max=Decimal(".7000000000000000001"), pending=False,
    )
    scenarios.update(response, 1)
    scenarios.start("pump", id_)
    assert "Aguardando comando" in scenarios.snapshot()[2]
    events = [SimulatedTelemetryGenerator(settings, vials).next_event()]
    adjusted, scenario = scenarios.adjust(events)
    assert .7 < adjusted[0].value <= .8
    assert scenarios.pump_failure(str(vials[1].allocation_id)) is None
    assert scenarios.pump_failure(id_) is scenario
    scenarios.failure_written(scenario)
    assert "Falha aplicada" in scenarios.snapshot()[2]
    now[0] = 60
    assert scenarios.pump_failure(id_) is None
    scenarios.update(response, 61)
    scenarios.start("pause", id_)
    replacement = vials[0].model_copy(update={"allocation_id": uuid4()})
    assert scenarios.update(response.model_copy(update={"vials": [replacement, vials[1]]}), 61)
    assert scenarios.hold(.5) is None
