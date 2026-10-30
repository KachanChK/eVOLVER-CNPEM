"""Transporte MQTT 5 para telemetria simulada."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt
from evolver_contracts.models import TelemetryEvent

from .config import SimulatorSettings

LOGGER = logging.getLogger(__name__)
ClientFactory = Callable[..., mqtt.Client]


class MqttConnectionError(RuntimeError):
    """Falha ao estabelecer uma sessao MQTT autenticada."""


class MqttPublishError(RuntimeError):
    """Falha ao confirmar a publicacao no transporte MQTT."""


class MqttPublisher:
    """Publica ``TelemetryEvent`` com MQTT 5, QoS 1 e sem retencao."""

    def __init__(
        self,
        settings: SimulatorSettings,
        *,
        client_factory: ClientFactory = mqtt.Client,
    ) -> None:
        self._settings = settings
        self._connect_finished = threading.Event()
        self._connected = threading.Event()
        self._connect_error: str | None = None
        self._loop_started = False
        self._client = client_factory(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv5,
        )
        self._client.username_pw_set(settings.mqtt_username, settings.mqtt_simulator_password)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    def _on_connect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            self._connect_error = str(reason_code)
        else:
            self._connected.set()
        self._connect_finished.set()

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        _reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        self._connected.clear()

    def connect(self) -> None:
        self._connect_finished.clear()
        self._connected.clear()
        self._connect_error = None
        try:
            result = self._client.connect(
                self._settings.mqtt_host,
                self._settings.mqtt_port,
                self._settings.mqtt_keepalive_seconds,
                clean_start=mqtt.MQTT_CLEAN_START_FIRST_ONLY,
            )
        except (OSError, mqtt.WebsocketConnectionError) as exc:
            raise MqttConnectionError(f"could not connect to MQTT broker: {exc}") from exc
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise MqttConnectionError(f"MQTT connect returned error code {result}")

        self._client.loop_start()
        self._loop_started = True
        if not self._connect_finished.wait(self._settings.mqtt_connect_timeout_seconds):
            self.close()
            raise MqttConnectionError("timed out waiting for MQTT CONNACK")
        if self._connect_error is not None:
            error = self._connect_error
            self.close()
            raise MqttConnectionError(f"MQTT connection refused: {error}")

        LOGGER.info(
            "Conectado ao broker MQTT em %s:%s como %s",
            self._settings.mqtt_host,
            self._settings.mqtt_port,
            self._settings.mqtt_username,
        )

    def publish(self, event: TelemetryEvent) -> None:
        if not self._connected.is_set():
            raise MqttPublishError("MQTT client is not connected")

        info = self._client.publish(
            self._settings.telemetry_topic,
            payload=event.model_dump_json(),
            qos=1,
            retain=False,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise MqttPublishError(f"MQTT publish returned error code {info.rc}")
        try:
            info.wait_for_publish(timeout=self._settings.mqtt_publish_timeout_seconds)
        except RuntimeError as exc:
            raise MqttPublishError(f"MQTT publication failed: {exc}") from exc
        if not info.is_published():
            raise MqttPublishError("timed out waiting for MQTT PUBACK")

        LOGGER.info(
            "Telemetria publicada event_id=%s sequence=%s vial_id=%s topic=%s",
            event.event_id,
            event.sequence,
            event.vial_id,
            self._settings.telemetry_topic,
        )

    def close(self) -> None:
        self._connected.clear()
        if not self._loop_started:
            return
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()
            self._loop_started = False
