from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import paho.mqtt.client as mqtt
import pytest
from evolver.ingestion.control import action_for_od
from evolver_contracts.models import PumpCommand, TelemetryAcknowledgement, TelemetryEvent
from evolver_contracts.pilot import (
    ACTIVE_VIALS_REQUEST,
    ACTIVE_VIALS_RESPONSE,
    TELEMETRY_MODE_PROPERTY,
    ActiveVial,
)
from evolver_simulator.config import SimulatorSettings
from evolver_simulator.mqtt import MqttConnectionError, MqttPublisher, MqttPublishError
from evolver_simulator.runner import SimulatorRunner
from evolver_simulator.telemetry import SimulatedTelemetryGenerator

ALLOCATION_41 = str(UUID(int=41))
ALLOCATION_42 = str(UUID(int=42))


def allocation_payload(experiment_id: int = 41, vial_id: int = 1) -> dict[str, int | str]:
    return {
        "vial_id": vial_id, "experiment_id": experiment_id,
        "allocation_id": str(UUID(int=experiment_id)),
    }


class FakeReasonCode:
    def __init__(self, *, is_failure: bool = False) -> None:
        self.is_failure = is_failure

    def __str__(self) -> str:
        return "not authorized" if self.is_failure else "success"


class FakeMessageInfo:
    def __init__(
        self,
        *,
        rc: int = mqtt.MQTT_ERR_SUCCESS,
        published: bool = True,
        mid: int = 1,
        reason_code: FakeReasonCode | None = None,
        invoke_callback: bool = True,
    ) -> None:
        self.rc = rc
        self._published = published
        self.mid = mid
        self.reason_code = reason_code or FakeReasonCode()
        self.invoke_callback = invoke_callback
        self.wait_timeout: float | None = None

    def wait_for_publish(self, *, timeout: float) -> None:
        self.wait_timeout = timeout

    def is_published(self) -> bool:
        return self._published


class FakeClient:
    def __init__(
        self,
        *,
        connect_result: int = mqtt.MQTT_ERR_SUCCESS,
        connect_failure: bool = False,
        message_info: FakeMessageInfo | None = None,
        allocation_response: list[dict[str, int | str]] | None = None,
        wrong_request_id: bool = False,
        invalid_response: bool = False,
        auto_ack: bool = False,
        subscription_failure: bool = False,
    ) -> None:
        self.connect_result = connect_result
        self.connect_failure = connect_failure
        self.message_info = message_info
        self.auto_ack = auto_ack
        self.subscription_failure = subscription_failure
        self.allocation_response = allocation_response
        self.wrong_request_id = wrong_request_id
        self.invalid_response = invalid_response
        self.on_connect: Any = None
        self.on_disconnect: Any = None
        self.on_publish: Any = None
        self.on_subscribe: Any = None
        self.on_message: Any = None
        self.username: str | None = None
        self.password: str | None = None
        self.connect_call: tuple[Any, ...] | None = None
        self.publish_call: tuple[tuple[Any, ...], dict[str, Any]] | None = None
        self.publish_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        self.subscriptions: list[str] = []

    def username_pw_set(self, username: str, password: str) -> None:
        self.username = username
        self.password = password

    def max_inflight_messages_set(self, count: int) -> None:
        assert count > 128

    def max_queued_messages_set(self, count: int) -> None:
        assert count > 128

    def connect(self, *args: Any, **kwargs: Any) -> int:
        self.connect_call = (*args, kwargs)
        return self.connect_result

    def loop_start(self) -> None:
        self.loop_started = True
        self.on_connect(self, None, object(), FakeReasonCode(is_failure=self.connect_failure), None)

    def publish(self, *args: Any, **kwargs: Any) -> FakeMessageInfo:
        self.publish_call = (args, kwargs)
        self.publish_calls.append((args, kwargs))
        info = self.message_info or FakeMessageInfo(mid=len(self.publish_calls))
        if info.rc == mqtt.MQTT_ERR_SUCCESS and info.invoke_callback:
            self.on_publish(
                self,
                None,
                info.mid,
                info.reason_code,
                None,
            )
        if args[0] == ACTIVE_VIALS_REQUEST and self.allocation_response is not None:
            request_id = json.loads(kwargs["payload"])["request_id"]
            if self.wrong_request_id:
                request_id = "00000000-0000-4000-8000-000000000000"
            payload = json.dumps(
                {"request_id": request_id, "vials": self.allocation_response}
            ).encode()
            if self.invalid_response:
                payload = b"not-json"
            message = type(
                "Message",
                (),
                {
                    "topic": ACTIVE_VIALS_RESPONSE,
                    "retain": False,
                    "payload": payload,
                },
            )()
            self.on_message(self, None, message)
        if self.auto_ack and args[0].endswith("/telemetry"):
            event = TelemetryEvent.model_validate_json(kwargs["payload"])
            outcome = TelemetryAcknowledgement(
                schema_version="1.0", event_id=event.event_id, equipment_id=event.equipment_id,
                status="persisted", acknowledged_at=datetime.now(UTC),
            )
            message = mqtt.MQTTMessage(topic=f"{args[0]}/ack".encode())
            message.payload = outcome.model_dump_json().encode()
            self.on_message(self, None, message)
        return info

    def subscribe(self, topics) -> tuple[int, int]:
        for topic, options in topics:
            assert options.QoS == 1 and options.retainAsPublished
            self.subscriptions.append(topic)
        codes = [FakeReasonCode() for _topic in topics]
        codes[-1] = FakeReasonCode(is_failure=self.subscription_failure)
        self.on_subscribe(self, None, 1, codes, None)
        return mqtt.MQTT_ERR_SUCCESS, 1

    def disconnect(self) -> None:
        self.disconnected = True

    def loop_stop(self) -> None:
        self.loop_stopped = True


def make_settings(**overrides: object) -> SimulatorSettings:
    values: dict[str, object] = {"mqtt_simulator_password": "local-secret", **overrides}
    return SimulatorSettings(_env_file=None, **values)


@pytest.fixture(autouse=True)
def temporary_pump_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SIMULATOR_PUMP_STATE_PATH", str(tmp_path / "default.sqlite3"))


def make_event() -> TelemetryEvent:
    return TelemetryEvent(
        schema_version="1.0",
        event_id=UUID("33333333-3333-4333-8333-333333333333"),
        producer_id="simulator-local-01",
        equipment_id="evolver-sim-01",
        vial_id="vial-01",
        measurement_type="od",
        value=0.42,
        generated_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
        sequence=0,
    )


def test_client_uses_mqtt5_authenticated_identity_and_connection_parameters() -> None:
    fake = FakeClient()
    factory_call: dict[str, Any] = {}

    def factory(**kwargs: Any) -> FakeClient:
        factory_call.update(kwargs)
        return fake

    settings = make_settings()
    publisher = MqttPublisher(settings, client_factory=factory)
    publisher.connect()

    assert factory_call == {
        "callback_api_version": mqtt.CallbackAPIVersion.VERSION2,
        "client_id": "simulator-local-01-telemetry",
        "protocol": mqtt.MQTTv5,
        "reconnect_on_failure": False,
    }
    assert (fake.username, fake.password) == ("evolver-sim-01", "local-secret")
    assert fake.connect_call == (
        "127.0.0.1",
        1883,
        60,
        {"clean_start": True},
    )
    publisher.close()
    assert fake.disconnected and fake.loop_stopped


def test_active_vials_request_returns_correlated_allocations() -> None:
    fake = FakeClient(
        allocation_response=[
            {"vial_id": 1, "experiment_id": 41},
            {"vial_id": 3, "experiment_id": 43},
        ]
    )
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()
    found = publisher.active_vials()
    assert [(v.vial_id, v.experiment_id) for v in found] == [(1, 41), (3, 43)]
    assert fake.subscriptions == [
        "evolver/v1/evolver-sim-01/commands",
        "evolver/v1/evolver-sim-01/active-vials/response",
        "evolver/v1/evolver-sim-01/telemetry/ack",
        "evolver/v1/evolver-sim-01/telemetry/rejection",
    ]
    args, kwargs = fake.publish_calls[0]
    assert args == ("evolver/v1/evolver-sim-01/active-vials/request",)
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is False
    assert set(json.loads(kwargs["payload"])) == {"request_id"}
    publisher.close()


def test_empty_active_vials_is_valid() -> None:
    fake = FakeClient(allocation_response=[])
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()
    assert publisher.active_vials() == []
    publisher.close()


@pytest.mark.parametrize(
    ("experiment_id", "allocations", "expected"),
    [
        (ALLOCATION_41, [allocation_payload()], "executed"),
        ("41", [allocation_payload()], "rejected"),
        (ALLOCATION_41, [{"vial_id": 1, "experiment_id": 41}], "rejected"),
        (None, [allocation_payload()], "rejected"),
        (ALLOCATION_41, [], "rejected"),
        (ALLOCATION_41, [allocation_payload(42, 2)], "rejected"),
    ],
)
def test_pump_command_requires_current_experiment(
    experiment_id: str | None, allocations: list[dict[str, int | str]], expected: str,
    tmp_path: Path,
) -> None:
    fake = FakeClient(allocation_response=allocations)
    publisher = MqttPublisher(
        make_settings(pump_state_path=tmp_path / "pump.sqlite3"),
        client_factory=lambda **_kwargs: fake,
    )
    publisher.connect()
    now = datetime.now(UTC)
    command = PumpCommand(
        schema_version="1.0", command_id=uuid4(), equipment_id="evolver-sim-01",
        experiment_run_id=experiment_id, author_id="evolver-od-control",
        created_at=now, expires_at=now + timedelta(seconds=10),
        target_type="pump", pump_id=1, action="turn_on",
    )
    publisher._handle_command(command.model_dump_json().encode())
    publisher._handle_command(command.model_dump_json().encode())
    result_payloads = [
        json.loads(kwargs["payload"])
        for (args, kwargs) in fake.publish_calls
        if args[0] == "evolver/v1/evolver-sim-01/command-results"
    ]
    assert result_payloads[-1]["status"] == expected
    assert result_payloads[-1]["command_id"] == str(command.command_id)
    if expected == "executed":
        assert publisher._pump_states[ALLOCATION_41, 1]
    else:
        assert (ALLOCATION_41, 1) not in publisher._pump_states
    publisher.close()


def test_duplicate_pump_command_rechecks_allocation_without_applying_again(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="evolver_simulator.mqtt")
    fake = FakeClient(allocation_response=[allocation_payload()])
    publisher = MqttPublisher(
        make_settings(pump_state_path=tmp_path / "pump.sqlite3"),
        client_factory=lambda **_kwargs: fake,
    )
    publisher.connect()
    now = datetime.now(UTC)
    command = PumpCommand(
        schema_version="1.0", command_id=uuid4(), equipment_id="evolver-sim-01",
        experiment_run_id=ALLOCATION_41, author_id="evolver-od-control",
        created_at=now, expires_at=now + timedelta(seconds=10),
        target_type="pump", pump_id=1, action="turn_on",
    )
    payload = command.model_dump_json().encode()
    publisher._handle_command(payload)
    publisher._handle_command(payload)
    assert len([call for call in fake.publish_calls if call[0][0] == ACTIVE_VIALS_REQUEST]) == 2
    assert publisher._pump_states == {(ALLOCATION_41, 1): True}
    results = [
        json.loads(kwargs["payload"]) for args, kwargs in fake.publish_calls
        if args[0] == "evolver/v1/evolver-sim-01/command-results"
    ]
    assert [result["status"] for result in results] == ["received", "executed", "executed"]
    assert {result["command_id"] for result in results} == {str(command.command_id)}
    assert caplog.text.count("Ação turn_on aplicada ao grupo de bombas [1, 2, 3]") == 1
    publisher.close()


def test_disconnected_simulator_does_not_apply_a_pump_command(tmp_path: Path) -> None:
    fake = FakeClient(allocation_response=[allocation_payload()])
    publisher = MqttPublisher(
        make_settings(pump_state_path=tmp_path / "pump.sqlite3"),
        client_factory=lambda **_kwargs: fake,
    )
    publisher.connect()
    publisher._on_disconnect(fake, None, object(), FakeReasonCode(), None)
    now = datetime.now(UTC)
    command = PumpCommand(
        schema_version="1.0", command_id=uuid4(), equipment_id="evolver-sim-01",
        experiment_run_id=ALLOCATION_41, author_id="evolver-od-control",
        created_at=now, expires_at=now + timedelta(seconds=10),
        target_type="pump", pump_id=1, action="turn_on",
    )
    publisher._handle_command(command.model_dump_json().encode())
    assert publisher._pump_states == {}
    publisher.close()


@pytest.mark.parametrize("pump_id", [1, 2, 3])
def test_expired_or_individually_targeted_command_leaves_group_off(
    pump_id: int, caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeClient(allocation_response=[allocation_payload()])
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()
    try:
        now = datetime.now(UTC)
        expires_at = now - timedelta(seconds=1) if pump_id == 1 else now + timedelta(seconds=10)
        command = PumpCommand(
            schema_version="1.0", command_id=uuid4(), equipment_id="evolver-sim-01",
            experiment_run_id=ALLOCATION_41, author_id="evolver-od-control",
            created_at=now - timedelta(seconds=2), expires_at=expires_at,
            target_type="pump", pump_id=1, action="turn_on",
        )
        payload = command.model_dump(mode="json")
        payload["pump_id"] = pump_id
        publisher._handle_command(json.dumps(payload).encode())

        assert publisher._pump_states == {}
        with closing(publisher._state_database()) as database:
            assert database.execute("SELECT * FROM allocation_pump_states").fetchall() == []
        results = [
            json.loads(kwargs["payload"]) for args, kwargs in fake.publish_calls
            if args[0] == "evolver/v1/evolver-sim-01/command-results"
        ]
        if pump_id == 1:
            result, = results
            assert (result["command_id"], result["status"], result["reason_code"]) == (
                str(command.command_id), "rejected", "expired",
            )
        else:
            assert results == []
            assert "Comando do grupo de bombas inválido" in caplog.text
    finally:
        publisher.close()


def test_pump_state_survives_restart_and_stays_isolated_by_experiment(
    tmp_path: Path,
) -> None:
    settings = make_settings(pump_state_path=tmp_path / "pump.sqlite3", od_noise=0)
    now = datetime.now(UTC)

    def command(experiment_id: str, action: str) -> PumpCommand:
        issued_at = now + timedelta(microseconds=1) if action == "turn_off" else now
        return PumpCommand(
            schema_version="1.0", command_id=uuid4(), equipment_id="evolver-sim-01",
            experiment_run_id=experiment_id, author_id="evolver-od-control",
            created_at=issued_at, expires_at=issued_at + timedelta(seconds=10),
            target_type="pump", pump_id=1, action=action,
        )

    fake = FakeClient(allocation_response=[allocation_payload()])
    first = MqttPublisher(settings, client_factory=lambda **_kwargs: fake)
    first.connect()
    turn_on = command(ALLOCATION_41, "turn_on")
    first._handle_command(turn_on.model_dump_json().encode())
    assert first._pump_states == {(ALLOCATION_41, 1): True}
    first.close()

    restarted_fake = FakeClient(allocation_response=[allocation_payload()])
    restarted = MqttPublisher(settings, client_factory=lambda **_kwargs: restarted_fake)
    restarted.connect()
    assert restarted._pump_states == {(ALLOCATION_41, 1): True}
    allocation = ActiveVial.model_validate(allocation_payload())
    assert restarted.pump_is_on(allocation)
    assert not restarted.pump_is_on(ActiveVial(vial_id=1, experiment_id=42))
    assert not restarted.pump_is_on(ActiveVial.model_validate(allocation_payload(41, 2)))
    generator = SimulatedTelemetryGenerator(
        settings, [allocation], pump_is_on=restarted.pump_is_on,
    )

    def sample_od() -> float:
        od, _, _ = (generator.next_event() for _ in range(3))
        return od.value

    assert sample_od() == 0.35
    assert sample_od() == 0.30
    restarted._handle_command(turn_on.model_dump_json().encode())
    assert restarted._pump_states == {(ALLOCATION_41, 1): True}
    assert json.loads(restarted_fake.publish_calls[-1][1]["payload"])["status"] == "executed"
    restarted._handle_command(command(ALLOCATION_41, "turn_off").model_dump_json().encode())
    assert restarted._pump_states == {(ALLOCATION_41, 1): False}
    # The controller uses this same turn_off command when it pauses the experiment.
    assert sample_od() == 0.32
    restarted.close()

    next_fake = FakeClient(allocation_response=[allocation_payload(42)])
    next_run = MqttPublisher(settings, client_factory=lambda **_kwargs: next_fake)
    next_run.connect()
    next_run._handle_command(command(ALLOCATION_42, "turn_on").model_dump_json().encode())
    assert next_run._pump_states == {(ALLOCATION_41, 1): False, (ALLOCATION_42, 1): True}
    next_run.close()


def test_simulator_handles_turn_off_after_a_pending_turn_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="evolver_simulator.mqtt")
    fake = FakeClient(allocation_response=[allocation_payload()])
    publisher = MqttPublisher(
        make_settings(pump_state_path=tmp_path / "pump.sqlite3"),
        client_factory=lambda **_kwargs: fake,
    )
    publisher.connect()
    try:
        now = datetime.now(UTC)
        command_ids = []
        for index, action in enumerate(("turn_on", "turn_off")):
            command = PumpCommand(
                schema_version="1.0", command_id=uuid4(), equipment_id="evolver-sim-01",
                experiment_run_id=ALLOCATION_41, author_id="evolver-od-control",
                created_at=now + timedelta(microseconds=index),
                expires_at=now + timedelta(seconds=10),
                target_type="pump", pump_id=1, action=action,
            )
            command_ids.append(str(command.command_id))
            message = mqtt.MQTTMessage(topic=b"evolver/v1/evolver-sim-01/commands")
            message.payload = command.model_dump_json().encode()
            publisher._on_message(fake, None, message)
        publisher._command_executor.submit(lambda: None).result(timeout=5)
        results = [
            json.loads(kwargs["payload"]) for args, kwargs in fake.publish_calls
            if args[0] == "evolver/v1/evolver-sim-01/command-results"
        ]
        assert [(r["command_id"], r["status"]) for r in results] == [
            (command_id, status)
            for command_id in command_ids for status in ("received", "executed")
        ]
        assert [r.getMessage() for r in caplog.records if "grupo de bombas" in r.getMessage()] == [
            f"Ação {action} aplicada ao grupo de bombas [1, 2, 3] (command_id={command_id})"
            for action, command_id in zip(("turn_on", "turn_off"), command_ids, strict=True)
        ]
        assert publisher._pump_states == {(ALLOCATION_41, 1): False}
    finally:
        publisher.close()


@pytest.mark.parametrize("restart_before_redelivery", [False, True])
def test_reconnect_delivers_older_on_after_newer_off(
    tmp_path: Path, restart_before_redelivery: bool,
) -> None:
    settings = make_settings(pump_state_path=tmp_path / "pump.sqlite3")
    now = datetime.now(UTC)

    def make_command(experiment: str, action: str, offset: int) -> PumpCommand:
        return PumpCommand(
            schema_version="1.0", command_id=uuid4(), equipment_id="evolver-sim-01",
            experiment_run_id=experiment, author_id="evolver-od-control",
            created_at=now + timedelta(microseconds=offset),
            expires_at=now + timedelta(seconds=10), target_type="pump", pump_id=1,
            action=action,
        )

    fake = FakeClient(allocation_response=[allocation_payload()])
    publisher = MqttPublisher(settings, client_factory=lambda **_kwargs: fake)
    publisher.connect()
    old_on = make_command(ALLOCATION_41, "turn_on", 1)
    applied_on = make_command(ALLOCATION_41, "turn_on", 0)
    off = make_command(ALLOCATION_41, "turn_off", 2)
    publisher._handle_command(applied_on.model_dump_json().encode())
    fake.on_disconnect(fake, None, object(), FakeReasonCode(), None)
    fake.on_connect(fake, None, object(), FakeReasonCode(), None)
    publisher._handle_command(off.model_dump_json().encode())
    if restart_before_redelivery:
        publisher.close()
        fake = FakeClient(allocation_response=[allocation_payload()])
        publisher = MqttPublisher(settings, client_factory=lambda **_kwargs: fake)
        publisher.connect()
    try:
        for command, status in [
            (old_on, "rejected"), (old_on, "rejected"), (applied_on, "executed"),
            (off, "executed"),
        ]:
            publisher._handle_command(command.model_dump_json().encode())
            result = json.loads(fake.publish_calls[-1][1]["payload"])
            assert (result["command_id"], result["status"]) == (str(command.command_id), status)
            assert publisher._pump_states == {(ALLOCATION_41, 1): False}
        fake.allocation_response = [allocation_payload(42)]
        reusable = make_command(ALLOCATION_42, "turn_on", 0)
        publisher._handle_command(reusable.model_dump_json().encode())
        assert publisher._pump_states == {(ALLOCATION_41, 1): False, (ALLOCATION_42, 1): True}
    finally:
        publisher.close()


@pytest.mark.parametrize("legacy_sqlite", [False, True])
def test_recreated_database_can_reuse_numeric_ids(
    tmp_path: Path, legacy_sqlite: bool,
) -> None:
    path = tmp_path / "pump.sqlite3"
    settings = make_settings(pump_state_path=path, od_noise=0)
    old = allocation_payload(1)
    new = {**old, "allocation_id": str(uuid4())}
    now = datetime.now(UTC)
    previous = PumpCommand(
        schema_version="1.0", command_id=uuid4(), equipment_id=settings.equipment_id,
        experiment_run_id="1" if legacy_sqlite else str(old["allocation_id"]),
        author_id="evolver-od-control", created_at=now, expires_at=now + timedelta(seconds=10),
        target_type="pump", pump_id=1, action="turn_on",
    )
    if legacy_sqlite:
        with closing(sqlite3.connect(path)) as database, database:
            database.executescript("""
                CREATE TABLE pump_states (experiment_id INTEGER, vial_id INTEGER, is_on INTEGER,
                    PRIMARY KEY (experiment_id, vial_id));
                INSERT INTO pump_states VALUES (1, 1, 1);
                CREATE TABLE pump_command_order (experiment_id INTEGER PRIMARY KEY,
                    issued_at TEXT NOT NULL);
                CREATE TABLE completed_commands (command_id TEXT PRIMARY KEY, status TEXT,
                    reason TEXT);
            """)
            database.execute("INSERT INTO pump_command_order VALUES (1, ?)", (now.isoformat(),))
            database.execute(
                "INSERT INTO completed_commands VALUES (?, 'executed', NULL)",
                (str(previous.command_id),),
            )
    else:
        old_client = FakeClient(allocation_response=[old])
        first = MqttPublisher(settings, client_factory=lambda **_kwargs: old_client)
        first.connect()
        try:
            first._handle_command(previous.model_dump_json().encode())
            assert first.pump_is_on(ActiveVial.model_validate(old))
        finally:
            first.close()

    fake = FakeClient(allocation_response=[new])
    restarted = MqttPublisher(settings, client_factory=lambda **_kwargs: fake)
    restarted.connect()
    try:
        allocation = restarted.active_vials()[0]
        assert (allocation.experiment_id, allocation.vial_id) == (1, 1)
        assert not restarted.pump_is_on(allocation)
        generator = SimulatedTelemetryGenerator(
            settings, [allocation], pump_is_on=restarted.pump_is_on,
        )
        events = [generator.next_event() for _ in range(6)]
        assert [event.value for event in events if event.measurement_type == "od"] == [0.35, 0.37]
        delayed = previous.model_copy(update={"command_id": uuid4()})
        for command in (previous, delayed):
            restarted._handle_command(command.model_dump_json().encode())
            result = json.loads(fake.publish_calls[-1][1]["payload"])
            assert (result["command_id"], result["status"]) == (str(command.command_id), "rejected")
            assert not restarted.pump_is_on(allocation)
        current = previous.model_copy(update={
            "command_id": uuid4(),
            "experiment_run_id": new["allocation_id"],
            "created_at": now - timedelta(seconds=1),
        })
        restarted._handle_command(current.model_dump_json().encode())
        result = json.loads(fake.publish_calls[-1][1]["payload"])
        assert (result["command_id"], result["status"]) == (str(current.command_id), "executed")
        assert restarted.pump_is_on(allocation)
    finally:
        restarted.close()


def test_pump_command_is_not_executed_when_state_cannot_be_saved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="evolver_simulator.mqtt")
    fake = FakeClient(allocation_response=[allocation_payload()])
    publisher = MqttPublisher(
        make_settings(),
        client_factory=lambda **_kwargs: fake,
    )
    publisher.connect()

    with closing(publisher._state_database()) as database, database:
        database.execute("""
            CREATE TRIGGER fail_completed_command BEFORE INSERT ON completed_allocation_commands
            BEGIN SELECT RAISE(ABORT, 'unavailable'); END
        """)
    now = datetime.now(UTC)
    command = PumpCommand(
        schema_version="1.0", command_id=uuid4(), equipment_id="evolver-sim-01",
        experiment_run_id=ALLOCATION_41, author_id="evolver-od-control",
        created_at=now, expires_at=now + timedelta(seconds=10),
        target_type="pump", pump_id=1, action="turn_on",
    )
    publisher._handle_command(command.model_dump_json().encode())
    assert publisher._pump_states == {}
    assert "Estado do grupo de bombas não persistido" in caplog.text
    assert "aplicada ao grupo de bombas" not in caplog.text
    with closing(publisher._state_database()) as database:
        assert database.execute("SELECT * FROM allocation_pump_states").fetchall() == []
        assert database.execute("SELECT * FROM allocation_pump_order").fetchall() == []
    assert not any(
        args[0] == "evolver/v1/evolver-sim-01/command-results"
        for args, _kwargs in fake.publish_calls
    )
    publisher.close()


def test_simulator_does_not_connect_if_persisted_state_is_unavailable(tmp_path: Path) -> None:
    fake = FakeClient()
    publisher = MqttPublisher(
        make_settings(pump_state_path=tmp_path),  # A directory cannot be opened as SQLite.
        client_factory=lambda **_kwargs: fake,
    )
    with pytest.raises(MqttConnectionError, match="carregar o estado do grupo de bombas"):
        publisher.connect()
    assert fake.connect_call is None


@pytest.mark.parametrize(("minimum", "maximum"), [("0.10", "0.80"), ("0.400", "0.401")])
def test_od_completes_two_controller_cycles(
    minimum: str, maximum: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("evolver_simulator.runner.ROUND_INTERVAL_SECONDS", 0.05)
    fake = FakeClient(allocation_response=[allocation_payload()], auto_ack=True)
    settings = make_settings(seed=71, od_noise=0.01)
    publisher = MqttPublisher(settings, client_factory=lambda **_kwargs: fake)
    runner = SimulatorRunner(settings, publisher=publisher)
    state = "off"
    issued_at = datetime.now(UTC)
    previous = None
    actions = []
    thresholds = []
    original_publish = publisher.publish

    def publish(payload, *, session, live):
        nonlocal previous, state
        info = original_publish(payload, session=session, live=live)
        event = TelemetryEvent.model_validate_json(payload)
        if event.measurement_type != "od":
            return info
        value = event.value
        assert 0.10 <= value <= 0.80
        if previous is not None:
            if state == "on":
                assert value < previous
            else:
                assert value > previous
        previous = value
        if len(actions) == 4:
            assert state == "off"
            runner.stop()
            return info
        action = action_for_od(state, Decimal(str(value)), Decimal(minimum), Decimal(maximum))
        if action is None:
            return info
        now = issued_at + timedelta(microseconds=len(actions))
        command = PumpCommand(
            schema_version="1.0", command_id=uuid4(), equipment_id=settings.equipment_id,
            experiment_run_id=ALLOCATION_41, author_id="evolver-od-control", created_at=now,
            expires_at=now + timedelta(seconds=10), target_type="pump", pump_id=1, action=action,
        )
        message = mqtt.MQTTMessage(topic=f"evolver/v1/{settings.equipment_id}/commands".encode())
        message.payload = command.model_dump_json().encode()
        publisher._on_message(fake, None, message)
        publisher._command_executor.submit(lambda: None).result(timeout=5)
        results = [json.loads(call[1]["payload"]) for call in fake.publish_calls[-2:]]
        assert all(result["command_id"] == str(command.command_id) for result in results)
        assert all(result["simulated"] for result in results)
        assert [result["status"] for result in results] == ["received", "executed"]
        state = "on" if action == "turn_on" else "off"
        actions.append(action)
        thresholds.append(value)
        return info

    monkeypatch.setattr(publisher, "publish", publish)
    assert runner.run(max_messages=360) < 360
    assert actions == ["turn_on", "turn_off"] * 2
    print(f"limiares={minimum}/{maximum} transições={thresholds} próxima subida={previous}")


@pytest.mark.parametrize("response_kind", ["missing", "unmatched", "invalid"])
def test_unusable_response_fails_without_fallback(response_kind: str) -> None:
    fake = FakeClient(
        allocation_response=[allocation_payload()]
        if response_kind != "missing"
        else None,
        wrong_request_id=response_kind == "unmatched",
        invalid_response=response_kind == "invalid",
    )
    publisher = MqttPublisher(
        make_settings(mqtt_connect_timeout_seconds=0.001), client_factory=lambda **_kwargs: fake
    )
    publisher.connect()
    with pytest.raises(MqttConnectionError, match="timed out waiting for active vials"):
        publisher.active_vials()
    publisher.close()


@pytest.mark.parametrize("live", [False, True])
def test_publish_uses_original_json_and_transport_metadata(live: bool) -> None:
    fake = FakeClient()
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()
    original = make_event().model_dump_json()
    info = publisher.publish(original, session=publisher.session, live=live)

    assert len(fake.publish_calls) == 1
    args, kwargs = fake.publish_calls[0]
    assert args == ("evolver/v1/evolver-sim-01/telemetry",)
    assert kwargs["qos"] == 1 and kwargs["retain"] is False
    assert kwargs["payload"] == original
    properties = kwargs["properties"]
    assert properties.UserProperty == [(TELEMETRY_MODE_PROPERTY, "live" if live else "history")]
    assert getattr(properties, "MessageExpiryInterval", None) == (2 if live else None)
    assert info.wait_timeout is None
    assert not publisher.publish_outcome(info, publisher.session).is_failure
    publisher.close()


def test_negative_mqtt5_puback_is_reported_as_transport_failure() -> None:
    fake = FakeClient(message_info=FakeMessageInfo(reason_code=FakeReasonCode(is_failure=True)))
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()
    info = publisher.publish(make_event().model_dump_json(), session=publisher.session, live=True)
    assert publisher.publish_outcome(info, publisher.session).is_failure
    assert list(publisher.outcomes()) == []
    publisher.close()


def test_connect_return_code_failure_is_reported_without_starting_loop() -> None:
    fake = FakeClient(connect_result=mqtt.MQTT_ERR_NO_CONN)
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    with pytest.raises(MqttConnectionError, match="error code"):
        publisher.connect()
    assert not fake.loop_started


@pytest.mark.parametrize("failure", ["connect_failure", "subscription_failure"])
def test_connect_or_subscription_failure_closes_transport(failure: str) -> None:
    fake = FakeClient(**{failure: True})
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    with pytest.raises(MqttConnectionError):
        publisher.connect()
    assert fake.disconnected and fake.loop_stopped and publisher.session is None


def test_publish_failure_is_reported() -> None:
    fake = FakeClient(message_info=FakeMessageInfo(rc=mqtt.MQTT_ERR_NO_CONN))
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()
    with pytest.raises(MqttPublishError):
        publisher.publish(make_event().model_dump_json(), session=publisher.session, live=True)
    publisher.close()


def test_application_outcome_requires_valid_identity_topic_version_and_no_retain() -> None:
    fake = FakeClient()
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()
    event = make_event()
    ack = TelemetryAcknowledgement(
        schema_version="1.0", event_id=event.event_id, equipment_id=event.equipment_id,
        status="persisted", acknowledged_at=datetime.now(UTC),
    )
    topic = f"evolver/v1/{event.equipment_id}/telemetry/ack"
    for topic_override, payload, retained in [
        (topic, ack.model_dump_json(), True),
        (topic, ack.model_copy(update={"equipment_id": "other"}).model_dump_json(), False),
        (topic, ack.model_copy(update={"schema_version": "2.0"}).model_dump_json(), False),
        (f"{topic}x", ack.model_dump_json(), False),
        (topic, ack.model_dump_json(), False),
    ]:
        message = mqtt.MQTTMessage(topic=topic_override.encode())
        message.payload = payload.encode()
        message.retain = retained
        fake.on_message(fake, None, message)
    assert list(publisher.outcomes()) == [ack]
    publisher.close()


def test_reconnect_creates_a_fresh_client() -> None:
    first, second = FakeClient(), FakeClient()
    clients = iter((first, second))
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: next(clients))
    publisher.connect()
    old_session = publisher.session
    publisher.connect()
    assert first.disconnected and first.loop_stopped and second.loop_started
    with pytest.raises(MqttConnectionError):
        publisher.publish(make_event().model_dump_json(), session=old_session, live=True)
    publisher.close()
