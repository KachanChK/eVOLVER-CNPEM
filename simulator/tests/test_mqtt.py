from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import paho.mqtt.client as mqtt
import pytest
from evolver_contracts.models import TelemetryEvent
from evolver_contracts.pilot import ACTIVE_VIALS_REQUEST, ACTIVE_VIALS_RESPONSE
from evolver_simulator.config import SimulatorSettings
from evolver_simulator.mqtt import MqttConnectionError, MqttPublisher, MqttPublishError


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
        allocation_response: list[dict[str, int]] | None = None,
        wrong_request_id: bool = False,
        invalid_response: bool = False,
    ) -> None:
        self.connect_result = connect_result
        self.connect_failure = connect_failure
        self.message_info = message_info or FakeMessageInfo()
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

    def connect(self, *args: Any, **kwargs: Any) -> int:
        self.connect_call = (*args, kwargs)
        return self.connect_result

    def loop_start(self) -> None:
        self.loop_started = True
        self.on_connect(self, None, object(), FakeReasonCode(is_failure=self.connect_failure), None)

    def publish(self, *args: Any, **kwargs: Any) -> FakeMessageInfo:
        self.publish_call = (args, kwargs)
        self.publish_calls.append((args, kwargs))
        if self.message_info.rc == mqtt.MQTT_ERR_SUCCESS and self.message_info.invoke_callback:
            self.on_publish(
                self,
                None,
                self.message_info.mid,
                self.message_info.reason_code,
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
        return self.message_info

    def subscribe(self, topic: str, qos: int) -> tuple[int, int]:
        assert qos == 1
        self.subscriptions.append(topic)
        self.on_subscribe(self, None, 1, [FakeReasonCode()], None)
        return mqtt.MQTT_ERR_SUCCESS, 1

    def disconnect(self) -> None:
        self.disconnected = True

    def loop_stop(self) -> None:
        self.loop_stopped = True


def make_settings(**overrides: object) -> SimulatorSettings:
    values: dict[str, object] = {"mqtt_simulator_password": "local-secret", **overrides}
    return SimulatorSettings(_env_file=None, **values)


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
    }
    assert (fake.username, fake.password) == ("evolver-sim-01", "local-secret")
    assert fake.connect_call == (
        "127.0.0.1",
        1883,
        60,
        {"clean_start": mqtt.MQTT_CLEAN_START_FIRST_ONLY},
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
    assert fake.subscriptions == [ACTIVE_VIALS_RESPONSE]
    assert fake.publish_calls[0][0] == (ACTIVE_VIALS_REQUEST,)
    publisher.close()


def test_empty_active_vials_is_valid() -> None:
    fake = FakeClient(allocation_response=[])
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()
    assert publisher.active_vials() == []
    publisher.close()


@pytest.mark.parametrize("response_kind", ["missing", "unmatched", "invalid"])
def test_unusable_response_fails_without_fallback(response_kind: str) -> None:
    fake = FakeClient(
        allocation_response=[{"vial_id": 1, "experiment_id": 41}]
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


def test_publish_uses_contract_json_topic_qos_one_and_no_retain() -> None:
    fake = FakeClient()
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()

    publisher.publish(make_event())

    assert fake.publish_call is not None
    args, kwargs = fake.publish_call
    assert args == ("evolver/v1/evolver-sim-01/telemetry",)
    assert kwargs["qos"] == 1
    assert kwargs["retain"] is False
    assert json.loads(kwargs["payload"])["measurement_type"] == "od"
    assert fake.message_info.wait_timeout == 10.0
    assert len(fake.publish_calls) == 1


@pytest.mark.parametrize(
    ("measurement_type", "value", "expected"),
    [
        ("od", 0.42, "Frasco 1 | OD: 0.42 | Enviado ao MQTT"),
        ("ph", 7.1, "Frasco 1 | pH: 7.1 | Enviado ao MQTT"),
        ("temperature", 37.5, "Frasco 1 | Temperatura: 37.5 °C | Enviado ao MQTT"),
    ],
)
def test_published_measurement_is_shown_in_the_terminal(
    measurement_type: str, value: float, expected: str, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeClient()
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()
    event = make_event().model_copy(
        update={"vial_id": "1", "measurement_type": measurement_type, "value": value}
    )

    with caplog.at_level(logging.INFO, logger="evolver_simulator.mqtt"):
        publisher.publish(event)

    assert expected in caplog.text


def test_temperature_is_sent_once_in_the_v1_format() -> None:
    fake = FakeClient()
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()
    event = make_event().model_copy(
        update={"vial_id": "42", "measurement_type": "temperature", "value": 37.5},
    )

    publisher.publish(event)

    assert len(fake.publish_calls) == 1
    (args, kwargs) = fake.publish_calls[0]
    assert args == ("evolver/v1/evolver-sim-01/telemetry",)
    assert kwargs["qos"] == 1 and kwargs["retain"] is False
    sent = json.loads(kwargs["payload"])
    assert sent["measurement_type"] == "temperature"
    assert sent["vial_id"] == "42" and sent["value"] == 37.5


def test_negative_mqtt5_puback_is_reported_as_publish_failure() -> None:
    message_info = FakeMessageInfo(
        mid=17,
        reason_code=FakeReasonCode(is_failure=True),
    )
    fake = FakeClient(message_info=message_info)
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()

    with pytest.raises(MqttPublishError, match="PUBACK rejected message 17: not authorized"):
        publisher.publish(make_event())


def test_missing_puback_result_is_reported_as_publish_failure() -> None:
    fake = FakeClient(message_info=FakeMessageInfo(mid=23, invoke_callback=False))
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()

    with pytest.raises(MqttPublishError, match="PUBACK result missing for message 23"):
        publisher.publish(make_event())


def test_connect_return_code_failure_is_reported_without_starting_loop() -> None:
    fake = FakeClient(connect_result=mqtt.MQTT_ERR_NO_CONN)
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)

    with pytest.raises(MqttConnectionError, match="error code"):
        publisher.connect()

    assert not fake.loop_started


def test_connack_failure_is_reported_and_client_is_closed() -> None:
    fake = FakeClient(connect_failure=True)
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)

    with pytest.raises(MqttConnectionError, match="not authorized"):
        publisher.connect()

    assert fake.disconnected and fake.loop_stopped


@pytest.mark.parametrize(
    "message_info",
    [
        FakeMessageInfo(rc=mqtt.MQTT_ERR_NO_CONN),
        FakeMessageInfo(published=False),
    ],
)
def test_publish_failure_is_reported(message_info: FakeMessageInfo) -> None:
    fake = FakeClient(message_info=message_info)
    publisher = MqttPublisher(make_settings(), client_factory=lambda **_kwargs: fake)
    publisher.connect()

    with pytest.raises(MqttPublishError):
        publisher.publish(make_event())
