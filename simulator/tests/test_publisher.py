import json
from datetime import UTC, datetime

from evolver_simulator.__main__ import TOPIC, build_message


def test_builds_temperature_message_for_temporary_topic() -> None:
    generated_at = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

    message = build_message(generated_at)

    assert TOPIC == "evolver/dev/evolver-sim-01/telemetry"
    assert message == {
        "equipment_id": "evolver-sim-01",
        "measurement": "temperature",
        "value": 37.0,
        "unit": "celsius",
        "generated_at": "2026-11-03T12:00:00Z",
    }
    assert json.loads(json.dumps(message)) == message
