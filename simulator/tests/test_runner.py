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
        self.stopped = False
        self.stop_after_rounds: int | None = None

    def __call__(self) -> float:
        return self.now

    def is_set(self) -> bool:
        return self.stopped

    def set(self) -> None:
        self.stopped = True

    def wait(self, seconds: float) -> bool:
        self.now += seconds
        self.waits.append(self.now)
        return (
            self.stopped
            or self.stop_after_first
            or (self.stop_after_rounds is not None and len(self.waits) > self.stop_after_rounds)
        )


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


def test_continuous_run_exceeds_ten_rounds_until_interrupted() -> None:
    publisher = FakePublisher(vials((1, 41), (3, 43), (6, 46)))
    clock = FakeClock()
    clock.stop_after_rounds = 25
    runner = SimulatorRunner(settings(), publisher=publisher, stop_event=clock, clock=clock)

    assert runner.run() == 225
    assert clock.waits == [round_number * 0.5 for round_number in range(1, 27)]
    assert Counter((e.vial_id, e.measurement_type) for e in publisher.events) == {
        (str(vial), kind): 25 for vial in (1, 3, 6) for kind in ("od", "ph", "temperature")
    }
    assert {e.vial_id: e.experiment_run_id for e in publisher.events} == {
        "1": "41",
        "3": "43",
        "6": "46",
    }
    assert publisher.calls == ["connect"] + ["active_vials"] * 25
    assert publisher.closed


def test_no_active_vials_waits_until_interrupted() -> None:
    publisher = FakePublisher([])
    clock = FakeClock()
    clock.stop_after_rounds = 25
    runner = SimulatorRunner(settings(), publisher=publisher, stop_event=clock, clock=clock)
    assert runner.run() == 0
    assert publisher.calls.count("active_vials") == 25
    assert publisher.events == [] and publisher.closed


def test_limit_shortens_run() -> None:
    publisher = FakePublisher(vials((1, 41)))
    clock = FakeClock()
    runner = SimulatorRunner(settings(), publisher=publisher, stop_event=clock, clock=clock)
    assert runner.run(max_messages=3) == 3
    assert clock.waits == [0.5]


@pytest.mark.parametrize(("configured", "requested", "expected"), [(75, None, 75), (3, 74, 74)])
def test_optional_limits_can_exceed_old_limit(
    configured: int, requested: int | None, expected: int
) -> None:
    publisher = FakePublisher(vials((1, 41)))
    clock = FakeClock()
    # Bound the fake run so a regression cannot hang the test suite.
    clock.stop_after_rounds = 30
    runner = SimulatorRunner(
        settings(max_messages=configured), publisher=publisher, stop_event=clock, clock=clock
    )
    assert runner.run(max_messages=requested) == expected
    assert publisher.closed


def test_experiments_can_start_stop_and_reuse_vials_without_restarting() -> None:
    snapshots = iter([
        [], vials((1, 41)), vials((1, 41), (3, 43)), [], vials((1, 51)),
    ])

    class ChangingPublisher(FakePublisher):
        def active_vials(self) -> list[ActiveVial]:
            return next(snapshots)

    publisher = ChangingPublisher([])
    clock = FakeClock()
    clock.stop_after_rounds = 5
    runner = SimulatorRunner(settings(), publisher=publisher, stop_event=clock, clock=clock)
    assert runner.run() == 12
    assert [(e.vial_id, e.experiment_run_id, e.measurement_type) for e in publisher.events] == [
        (vial, experiment, kind)
        for vial, experiment in [("1", "41"), ("1", "41"), ("3", "43"), ("1", "51")]
        for kind in ("od", "ph", "temperature")
    ]
    assert [e.sequence for e in publisher.events] == list(range(12))
    assert publisher.closed


def test_stop_during_publication_does_not_send_rest_of_round() -> None:
    clock = FakeClock()

    class StoppingPublisher(FakePublisher):
        def publish(self, event: TelemetryEvent) -> None:
            super().publish(event)
            runner.stop()

    publisher = StoppingPublisher(vials((1, 41), (2, 42)))
    runner = SimulatorRunner(settings(), publisher=publisher, stop_event=clock, clock=clock)
    assert runner.run() == 1
    assert publisher.closed


def test_stop_during_configured_pause_closes_connection() -> None:
    clock = FakeClock()
    clock.stop_after_rounds = 1
    publisher = FakePublisher(vials((1, 41)))
    runner = SimulatorRunner(
        settings(pause_after_messages=1, pause_seconds=60),
        publisher=publisher, stop_event=clock, clock=clock,
    )
    assert runner.run() == 1
    assert publisher.closed


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
