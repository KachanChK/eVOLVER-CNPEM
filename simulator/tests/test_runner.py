from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from uuid import UUID

import pytest
from evolver_contracts.models import TelemetryEvent
from evolver_simulator.config import SimulatorSettings
from evolver_simulator.mqtt import MqttPublishError
from evolver_simulator.runner import SimulatedFailureError, SimulatorRunner


class FakeGenerator:
    def __init__(self) -> None:
        self.sequence = 0

    def next_event(self) -> TelemetryEvent:
        event = TelemetryEvent(
            schema_version="1.0",
            event_id=UUID(int=self.sequence + 1),
            producer_id="simulator-local-01",
            equipment_id="evolver-sim-01",
            vial_id="vial-01",
            measurement_type="od",
            value=0.4,
            generated_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
            sequence=self.sequence,
        )
        self.sequence += 1
        return event


class FakePublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.connected = False
        self.closed = False
        self.events: list[TelemetryEvent] = []

    def connect(self) -> None:
        self.connected = True

    def publish(self, event: TelemetryEvent) -> None:
        if self.fail:
            raise MqttPublishError("simulated failure")
        self.events.append(event)

    def close(self) -> None:
        self.closed = True


class StopOnFirstWait:
    def __init__(self) -> None:
        self.wait_timeouts: list[float] = []

    def is_set(self) -> bool:
        return False

    def wait(self, timeout: float) -> bool:
        self.wait_timeouts.append(timeout)
        return True


class RecordingWait:
    def __init__(self) -> None:
        self.wait_timeouts: list[float] = []

    def is_set(self) -> bool:
        return False

    def wait(self, timeout: float) -> bool:
        self.wait_timeouts.append(timeout)
        return False


def make_settings(**overrides: object) -> SimulatorSettings:
    values: dict[str, object] = {"mqtt_simulator_password": "local-secret", **overrides}
    return SimulatorSettings(_env_file=None, **values)


def test_finite_run_publishes_exact_limit_and_closes() -> None:
    publisher = FakePublisher()
    runner = SimulatorRunner(
        make_settings(interval_seconds=0.001),
        generator=FakeGenerator(),
        publisher=publisher,
    )

    count = runner.run(max_messages=3)

    assert count == 3
    assert [event.sequence for event in publisher.events] == [0, 1, 2]
    assert publisher.connected and publisher.closed


@pytest.mark.parametrize("vials", ["1", "2,5"])
def test_default_run_sends_three_of_each_measurement_per_vial(vials: str) -> None:
    publisher = FakePublisher()
    runner = SimulatorRunner(
        make_settings(vial_ids_csv=vials), publisher=publisher, stop_event=RecordingWait()
    )

    count = runner.run()

    counts = Counter((event.vial_id, event.measurement_type) for event in publisher.events)
    expected = {
        (vial, kind): 3 for vial in vials.split(",") for kind in ("od", "ph", "temperature")
    }
    assert count == 9 * len(vials.split(","))
    assert counts == expected
    assert publisher.connected and publisher.closed


@pytest.mark.parametrize("configured_limit,argument_limit", [(100, None), (None, 100)])
def test_larger_custom_limit_does_not_exceed_three_readings_per_type(
    configured_limit: int | None, argument_limit: int | None
) -> None:
    publisher = FakePublisher()
    runner = SimulatorRunner(
        make_settings(max_messages=configured_limit),
        publisher=publisher,
        stop_event=RecordingWait(),
    )

    count = runner.run(max_messages=argument_limit)

    assert count == 9
    assert Counter(event.measurement_type for event in publisher.events) == {
        "od": 3,
        "ph": 3,
        "temperature": 3,
    }


def test_stop_event_interrupts_interval_wait_and_closes() -> None:
    publisher = FakePublisher()
    stop_event = StopOnFirstWait()
    runner = SimulatorRunner(
        make_settings(interval_seconds=7),
        generator=FakeGenerator(),
        publisher=publisher,
        stop_event=stop_event,
    )

    count = runner.run()

    assert count == 1
    assert stop_event.wait_timeouts == [7.0]
    assert publisher.closed


def test_transport_failure_still_closes_publisher() -> None:
    publisher = FakePublisher(fail=True)
    runner = SimulatorRunner(
        make_settings(),
        generator=FakeGenerator(),
        publisher=publisher,
    )

    with pytest.raises(MqttPublishError, match="simulated failure"):
        runner.run(max_messages=1)

    assert publisher.closed


def test_configured_pause_replaces_one_regular_interval() -> None:
    publisher = FakePublisher()
    stop_event = RecordingWait()
    runner = SimulatorRunner(
        make_settings(
            interval_seconds=0.5,
            pause_after_messages=1,
            pause_seconds=7,
        ),
        generator=FakeGenerator(),
        publisher=publisher,
        stop_event=stop_event,
    )

    count = runner.run(max_messages=2)

    assert count == 2
    assert stop_event.wait_timeouts == [7.0]
    assert publisher.closed


def test_configured_failure_happens_after_exact_published_count_and_closes() -> None:
    publisher = FakePublisher()
    runner = SimulatorRunner(
        make_settings(fail_after_messages=2),
        generator=FakeGenerator(),
        publisher=publisher,
    )

    with pytest.raises(SimulatedFailureError, match="after 2 published messages"):
        runner.run(max_messages=5)

    assert [event.sequence for event in publisher.events] == [0, 1]
    assert publisher.closed
