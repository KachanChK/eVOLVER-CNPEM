from __future__ import annotations

from collections import Counter

import pytest
from evolver_contracts.models import TelemetryEvent
from evolver_contracts.pilot import ActiveVial
from evolver_simulator.config import SimulatorSettings
from evolver_simulator.mqtt import MqttConnectionError, MqttPublishError
from evolver_simulator.runner import SimulatedFailureError, SimulatorRunner


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []
        self.stop_after_first = False

    def __call__(self) -> float:
        return self.now

    def is_set(self) -> bool:
        return False

    def wait(self, seconds: float) -> bool:
        self.now += seconds
        self.waits.append(self.now)
        return self.stop_after_first


class FakePublisher:
    def __init__(self, vials: list[ActiveVial], *, fail: bool = False) -> None:
        self.vials = vials
        self.fail = fail
        self.closed = False
        self.events: list[TelemetryEvent] = []
        self.calls: list[str] = []

    def connect(self) -> None:
        self.calls.append("connect")

    def active_vials(self) -> list[ActiveVial]:
        self.calls.append("active_vials")
        return self.vials

    def publish(self, event: TelemetryEvent) -> None:
        if self.fail:
            raise MqttPublishError("simulated failure")
        self.events.append(event)

    def close(self) -> None:
        self.closed = True


def settings(**overrides: object) -> SimulatorSettings:
    return SimulatorSettings(_env_file=None, mqtt_simulator_password="local-secret", **overrides)


def vials(*pairs: tuple[int, int]) -> list[ActiveVial]:
    return [ActiveVial(vial_id=vial, experiment_id=experiment) for vial, experiment in pairs]


def test_ten_rounds_send_every_type_to_every_active_vial() -> None:
    publisher = FakePublisher(vials((1, 41), (3, 43), (6, 46)))
    clock = FakeClock()
    runner = SimulatorRunner(settings(), publisher=publisher, stop_event=clock, clock=clock)

    assert runner.run() == 90
    assert clock.waits == [round_number * 0.5 for round_number in range(1, 11)]
    assert Counter((e.vial_id, e.measurement_type) for e in publisher.events) == {
        (str(vial), kind): 10 for vial in (1, 3, 6) for kind in ("od", "ph", "temperature")
    }
    assert {e.vial_id: e.experiment_run_id for e in publisher.events} == {
        "1": "41",
        "3": "43",
        "6": "46",
    }
    assert publisher.calls == ["connect", "active_vials"]
    assert publisher.closed


def test_no_active_vials_sends_nothing() -> None:
    publisher = FakePublisher([])
    assert SimulatorRunner(settings(), publisher=publisher).run() == 0
    assert publisher.events == [] and publisher.closed


def test_limit_shortens_run() -> None:
    publisher = FakePublisher(vials((1, 41)))
    clock = FakeClock()
    runner = SimulatorRunner(settings(), publisher=publisher, stop_event=clock, clock=clock)
    assert runner.run(max_messages=3) == 3
    assert clock.waits == [0.5]


def test_interruption_stops_before_first_round() -> None:
    publisher = FakePublisher(vials((1, 41)))
    clock = FakeClock()
    clock.stop_after_first = True
    runner = SimulatorRunner(settings(), publisher=publisher, stop_event=clock, clock=clock)
    assert runner.run() == 0
    assert publisher.events == [] and publisher.closed


def test_publish_failure_and_simulated_failure_close_connection() -> None:
    clock = FakeClock()
    publisher = FakePublisher(vials((1, 41)), fail=True)
    runner = SimulatorRunner(settings(), publisher=publisher, stop_event=clock, clock=clock)
    with pytest.raises(MqttPublishError):
        runner.run()
    assert publisher.closed

    publisher = FakePublisher(vials((1, 41)))
    runner = SimulatorRunner(
        settings(fail_after_messages=2), publisher=publisher, stop_event=clock, clock=clock
    )
    with pytest.raises(SimulatedFailureError):
        runner.run()
    assert len(publisher.events) == 2 and publisher.closed


def test_discovery_failure_closes_connection() -> None:
    class FailingPublisher(FakePublisher):
        def active_vials(self) -> list[ActiveVial]:
            raise MqttConnectionError("no response")

    publisher = FailingPublisher([])
    with pytest.raises(MqttConnectionError):
        SimulatorRunner(settings(), publisher=publisher).run()
    assert publisher.closed and publisher.events == []
