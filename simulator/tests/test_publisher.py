import json
from datetime import UTC, datetime

from evolver_simulator import __main__ as publisher


def test_builds_temperature_message_for_temporary_topic() -> None:
    generated_at = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

    message = publisher.build_message(generated_at)

    assert publisher.EQUIPMENT_ID == "evolver-sim-01"
    assert publisher.TOPIC == "evolver/dev/evolver-sim-01/telemetry"
    assert message == {
        "equipment_id": "evolver-sim-01",
        "measurement": "temperature",
        "value": 37.0,
        "unit": "celsius",
        "generated_at": "2026-11-03T12:00:00Z",
    }
    assert json.loads(json.dumps(message)) == message


def test_rejects_failed_puback(monkeypatch, capsys) -> None:
    class FakeReasonCode:
        def __init__(self, is_failure: bool, description: str) -> None:
            self.is_failure = is_failure
            self.description = description

        def __str__(self) -> str:
            return self.description

    class FakePublication:
        @staticmethod
        def wait_for_publish(timeout: float) -> None:
            assert timeout == publisher.TIMEOUT_SECONDS

        @staticmethod
        def is_published() -> bool:
            return True

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["client_id"] == publisher.EQUIPMENT_ID
            self.on_connect = None
            self.on_publish = None

        def username_pw_set(self, username: str, password: str) -> None:
            assert username == publisher.EQUIPMENT_ID
            assert password == "simulator-local-only"

        def connect(self, host: str, port: int, keepalive: int) -> None:
            assert (host, port, keepalive) == ("127.0.0.1", 1883, 60)
            assert self.on_connect is not None
            self.on_connect(self, None, None, FakeReasonCode(False, "Success"), None)

        @staticmethod
        def loop_start() -> None:
            pass

        def publish(self, topic: str, payload: str, qos: int, retain: bool) -> FakePublication:
            assert topic == publisher.TOPIC
            assert json.loads(payload)["equipment_id"] == publisher.EQUIPMENT_ID
            assert (qos, retain) == (1, False)
            assert self.on_publish is not None
            self.on_publish(self, None, 1, FakeReasonCode(True, "Not authorized"), None)
            return FakePublication()

        @staticmethod
        def disconnect() -> None:
            pass

        @staticmethod
        def loop_stop() -> None:
            pass

    monkeypatch.setenv("MQTT_SIMULATOR_PASSWORD", "simulator-local-only")
    monkeypatch.setattr(publisher.mqtt, "Client", FakeClient)

    assert publisher.main() == 1

    captured = capsys.readouterr()
    assert "broker rejeitou a publicação: Not authorized" in captured.err
    assert "Mensagem enviada" not in captured.out
    assert "PUBACK recebido" not in captured.out
