from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import paho.mqtt.client as mqtt
import pytest
from evolver_contracts.models import TelemetryEvent
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
    ) -> None:
        self.connect_result = connect_result
        self.connect_failure = connect_failure
        self.message_info = message_info or FakeMessageInfo()
        self.on_connect: Any = None
        self.on_disconnect: Any = None
        self.on_publish: Any = None
        self.username: str | None = None
        self.password: str | None = None
        self.connect_call: tuple[Any, ...] | None = None
        self.publish_call: tuple[tuple[Any, ...], dict[str, Any]] | None = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False

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
        if self.message_info.rc == mqtt.MQTT_ERR_SUCCESS and self.message_info.invoke_callback:
            self.on_publish(
                self,
                None,
                self.message_info.mid,
                self.message_info.reason_code,
                None,
            )
        return self.message_info

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
