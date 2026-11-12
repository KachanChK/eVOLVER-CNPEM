import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from evolver_simulator import __main__ as publisher


@pytest.mark.parametrize(
    ("vials", "rejected", "expected"),
    [
        ([1, 7], False, [1, 7]),
        ([2], False, [2]),
        ([], False, []),
        (None, False, []),
        ([1], True, []),
    ],
)
def test_simulator_round(monkeypatch, capsys, vials, rejected, expected) -> None:
    sent = []
    success = SimpleNamespace(is_failure=False)

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def username_pw_set(self, username, password):
            assert username == publisher.EQUIPMENT_ID

        def connect(self, host, port, keepalive):
            self.on_connect(self, None, None, success, None)

        def subscribe(self, topic, qos):
            assert topic == publisher.ACTIVE_VIALS_RESPONSE
            self.on_subscribe(self, None, 1, [success], None)
            return publisher.mqtt.MQTT_ERR_SUCCESS, 1

        def publish(self, topic, payload, qos, retain):
            assert (qos, retain) == (1, False)
            data = json.loads(payload)
            code = SimpleNamespace(is_failure=True) if rejected else success
            self.on_publish(self, None, 1, code, None)
            if topic == publisher.ACTIVE_VIALS_REQUEST and vials is not None:
                for request_id in (str(uuid4()), data["request_id"]):
                    response = {
                        "request_id": request_id,
                        "vials": [{"vial_id": vial, "experiment_id": 20 + vial} for vial in vials],
                    }
                    self.on_message(
                        self,
                        None,
                        SimpleNamespace(
                            topic=publisher.ACTIVE_VIALS_RESPONSE,
                            payload=json.dumps(response).encode(),
                            retain=False,
                        ),
                    )
            if topic == publisher.TELEMETRY_TOPIC:
                sent.append(publisher.TemperatureMessage.model_validate(data))
            return SimpleNamespace(wait_for_publish=lambda timeout: None, is_published=lambda: True)

        def loop_start(self):
            pass

        def loop_stop(self):
            pass

        def disconnect(self):
            pass

    monkeypatch.setenv("MQTT_SIMULATOR_PASSWORD", "simulator-local-only")
    monkeypatch.setattr(publisher, "TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(publisher.mqtt, "Client", FakeClient)
    assert publisher.main() == int(vials is None or rejected)
    assert [message.vial_id for message in sent] == expected
    assert [message.experiment_id for message in sent] == [20 + vial for vial in expected]
    assert all(message.value == 37.0 for message in sent)
    if vials is None:
        assert "não respondeu" in capsys.readouterr().err
    if rejected:
        assert "broker rejeitou" in capsys.readouterr().err
