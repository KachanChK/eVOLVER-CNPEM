from __future__ import annotations

import sqlite3
from concurrent.futures import Future
from contextlib import closing
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from evolver_contracts.models import TelemetryAcknowledgement, TelemetryEvent, TelemetryRejection
from evolver_contracts.pilot import ActiveVial, AllocationResponse
from evolver_simulator.config import SimulatorSettings
from evolver_simulator.mqtt import AllocationQuery, MqttConnectionError
from evolver_simulator.queue import QueueIdentityError, TelemetryQueue
from evolver_simulator.runner import Delivery, SimulatedFailureError, SimulatorRunner
from evolver_simulator.telemetry import SimulatedTelemetryGenerator

VIAL = ActiveVial(vial_id=1, experiment_id=41, allocation_id=UUID(int=41))


class Clock:
    def __init__(self, stop_at=60.0):
        self.now = 0.0
        self.stop_at = stop_at

    def __call__(self):
        return self.now

    def is_set(self):
        return self.now >= self.stop_at

    def set(self):
        self.stop_at = self.now

    def wait(self, seconds):
        self.now += seconds


class InlineConnector:
    def __init__(self, _workers):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exception):
        pass

    def submit(self, connect):
        result = Future()
        try:
            result.set_result(connect())
        except MqttConnectionError as exc:
            result.set_exception(exc)
        return result


class PublishResult:
    is_failure = False


class Publisher:
    def __init__(self, *, offline=False, vials=(VIAL,), acknowledge=True):
        self.session = None
        self.offline = offline
        self.vials = list(vials)
        self.acknowledge = acknowledge
        self.sent = []
        self.responses = []
        self.closed = False

    def connect(self):
        if self.offline:
            raise MqttConnectionError("offline")
        self.session = 1

    def disconnect(self):
        self.session = None

    def close(self):
        self.closed = True

    def request_allocations(self, session):
        query = AllocationQuery(uuid4(), session)
        query.response = AllocationResponse(request_id=query.request_id, vials=self.vials)
        query.finished.set()
        return query

    def cancel_query(self, _query):
        pass

    def pump_is_on(self, _allocation):
        return False

    def publish(self, payload, *, session, live):
        assert session == self.session
        self.sent.append((payload, live))
        if self.acknowledge:
            self.responses.append(ack(TelemetryEvent.model_validate_json(payload)))
        return PublishResult()

    def publish_outcome(self, info, _session):
        return info

    def outcomes(self):
        responses, self.responses = self.responses, []
        return iter(responses)


def ack(event):
    return TelemetryAcknowledgement(
        schema_version="1.0", event_id=event.event_id, equipment_id=event.equipment_id,
        status="persisted", acknowledged_at=datetime.now(UTC),
    )


@pytest.fixture(autouse=True)
def inline_connection(monkeypatch):
    monkeypatch.setattr("evolver_simulator.runner.ThreadPoolExecutor", InlineConnector)


@pytest.fixture
def settings(tmp_path):
    return SimulatorSettings(
        _env_file=None, mqtt_simulator_password="test", pump_state_path=tmp_path / "pump.sqlite3",
        telemetry_queue_path=tmp_path / "queue.sqlite3", telemetry_queue_max_events=6,
    )


def prime(settings, vials):
    with closing(TelemetryQueue(settings)) as queue:
        queue.confirm_allocation(AllocationResponse(request_id=uuid4(), vials=vials))


def test_offline_restart_preserves_payload_and_recovers_independently_of_discovery(settings):
    prime(settings, [VIAL])
    producer = Publisher(offline=True)
    clock = Clock()
    assert SimulatorRunner(settings, publisher=producer, clock=clock, stop_event=clock).run(
        max_messages=4,
    ) == 4
    assert producer.sent == [] and producer.closed
    with closing(TelemetryQueue(settings)) as queue:
        assert queue.last_allocation().vials == [VIAL]
        original = [row["payload"] for row in queue.eligible(0, 2, 10, live=False)]
    receiver = Publisher(vials=[])
    clock = Clock(stop_at=2)
    assert SimulatorRunner(settings, publisher=receiver, clock=clock, stop_event=clock).run() == 0
    assert receiver.sent == [(payload, False) for payload in original]
    with closing(TelemetryQueue(settings)) as queue:
        assert queue.last_allocation().vials == []
        assert queue.stats() == (0, 0, None)
    clock = Clock(stop_at=2)
    assert SimulatorRunner(
        settings, publisher=Publisher(offline=True), clock=clock, stop_event=clock,
    ).run() == 0


def test_cli_counts_new_events_without_application_ack(settings):
    publisher = Publisher(acknowledge=False)
    clock = Clock()
    assert SimulatorRunner(settings, publisher=publisher, clock=clock, stop_event=clock).run(
        max_messages=2,
    ) == 2
    assert [live for _, live in publisher.sent] == [True, True]
    assert 5.5 <= clock.now < 5.6
    with closing(TelemetryQueue(settings)) as queue:
        assert queue.stats()[0] == 2


def test_failure_and_pause_use_exact_locally_committed_counts(settings):
    clock = Clock()
    crash = settings.model_copy(update={"fail_after_messages": 2})
    with pytest.raises(SimulatedFailureError, match="2 leituras"):
        SimulatorRunner(crash, publisher=Publisher(), clock=clock, stop_event=clock).run()
    with closing(TelemetryQueue(settings)) as queue:
        assert queue.stats()[0] == 2
    clock = Clock()
    paused = settings.model_copy(update={"pause_after_messages": 1, "pause_seconds": 7})
    publisher = Publisher()
    assert SimulatorRunner(paused, publisher=publisher, clock=clock, stop_event=clock).run(
        max_messages=3,
    ) == 3
    assert 7.5 <= clock.now < 7.7
    events = [TelemetryEvent.model_validate_json(payload) for payload, _ in publisher.sent]
    assert [event.sequence for event in events] == [0, 1, 0, 1, 2]


def test_puback_alone_keeps_pending_and_retry_preserves_json(settings):
    clock = Clock()
    publisher = Publisher(acknowledge=False)
    publisher.connect()
    event = SimulatedTelemetryGenerator(settings, [VIAL]).next_event()
    with closing(TelemetryQueue(settings)) as queue:
        assert queue.append([event], session=1, live_until=2)
        delivery = Delivery(queue, publisher, clock)
        delivery.step(0, 1)
        assert queue.stats()[0] == 1
        clock.now = 5
        delivery.step(5, 1)
        assert len(publisher.sent) == 1 and not delivery.waiting
        clock.now = 6
        delivery.step(6, 1)
        assert publisher.sent == [(event.model_dump_json(), True), (event.model_dump_json(), False)]
        publisher.responses.append(ack(event))
        delivery.step(6, 1)
        assert queue.stats() == (0, 0, None)


def test_quota_rejection_and_rollback_leave_prior_events_intact(settings):
    generator = SimulatedTelemetryGenerator(settings, [VIAL])
    events = [generator.next_event() for _ in range(6)]
    with closing(TelemetryQueue(settings)) as queue:
        assert queue.database.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert queue.database.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert queue.append(events[:3], session=None, live_until=0)
        with pytest.raises(sqlite3.IntegrityError):
            queue.append([events[3], events[0]], session=None, live_until=0)
        assert queue.stats()[0] == 3
        assert queue.append(events[3:], session=None, live_until=0)
        rejection = TelemetryRejection(
            schema_version="1.0", event_id=events[0].event_id, equipment_id=settings.equipment_id,
            disposition="quarantined", reason_code="invalid_origin", detail="alocação encerrada",
            rejected_at=datetime.now(UTC),
        )
        queue.apply([rejection])
        assert queue.stats()[:2] == (5, 1)
        assert not queue.append([generator.next_event()], session=None, live_until=0)
        assert queue.apply([ack(events[0])]) == []
        assert queue.apply([ack(events[1]).model_copy(update={"equipment_id": "wrong"})]) == []
        queue.apply([ack(events[1])])
        assert queue.append([generator.next_event()], session=None, live_until=0)
    with closing(TelemetryQueue(settings)) as queue:
        quarantined, = queue.database.execute("""
            SELECT payload, reason_code, detail FROM telemetry_queue WHERE rejected_at IS NOT NULL
        """).fetchall()
        assert tuple(quarantined) == (
            events[0].model_dump_json(), "invalid_origin", "alocação encerrada",
        )
    with pytest.raises(QueueIdentityError):
        TelemetryQueue(settings.model_copy(update={"producer_id": "new-producer"}))


def test_sqlite_full_and_failed_ack_deletion_allow_retry(settings):
    settings = settings.model_copy(update={"telemetry_queue_max_events": 1000})
    generator = SimulatedTelemetryGenerator(settings, [VIAL])
    first = generator.next_event()
    with closing(TelemetryQueue(settings)) as queue:
        assert queue.append([first], session=None, live_until=0)
        pages = queue.database.execute("PRAGMA page_count").fetchone()[0]
        queue.database.execute(f"PRAGMA max_page_count = {pages}")
        events = [generator.next_event() for _ in range(40)]
        with pytest.raises(sqlite3.OperationalError) as failure:
            queue.append(events, session=None, live_until=0)
        assert failure.value.sqlite_errorcode == sqlite3.SQLITE_FULL
        assert queue.stats()[0] == 1
        queue.database.execute("""
            CREATE TEMP TRIGGER fail_delete BEFORE DELETE ON telemetry_queue
            BEGIN SELECT raise(ABORT, 'delete failure'); END
        """)
        with pytest.raises(sqlite3.IntegrityError):
            queue.apply([ack(first)])
        assert queue.stats()[0] == 1
        queue.database.execute("DROP TRIGGER fail_delete")
        queue.database.execute(f"PRAGMA max_page_count = {pages + 100}")
        assert queue.append(events, session=None, live_until=0)
        assert queue.apply([ack(first)])
        assert queue.stats()[0] == len(events)


def test_invalid_local_bytes_are_isolated_before_sending_following_rows(settings):
    clock = Clock()
    publisher = Publisher()
    publisher.connect()
    events = [SimulatedTelemetryGenerator(settings, [VIAL]).next_event() for _ in range(2)]
    with closing(TelemetryQueue(settings)) as queue:
        queue.append(events, session=None, live_until=0)
        with queue.database:
            queue.database.execute(
                "UPDATE telemetry_queue SET payload = ? WHERE event_id = ?",
                (b"\xffinvalid", str(events[0].event_id)),
            )
        delivery = Delivery(queue, publisher, clock)
        delivery.step(0, 1)
        delivery.step(1, 1)
        assert queue.stats()[:2] == (0, 1)
        assert publisher.sent == [(events[1].model_dump_json(), False)]
