from __future__ import annotations

import os
import signal
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from evolver_contracts.models import TelemetryAcknowledgement, TelemetryEvent
from evolver_contracts.pilot import ActiveVial, AllocationResponse
from evolver_simulator import __main__ as cli
from evolver_simulator.mqtt import AllocationQuery
from evolver_simulator.runner import SimulatorRunner


@pytest.mark.parametrize("stop_signal", [signal.SIGINT, signal.SIGTERM])
def test_cli_stops_cleanly_on_signal_and_restores_handlers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stop_signal: signal.Signals
) -> None:
    for name in list(os.environ):
        if name.startswith(("MQTT_", "SIMULATOR_")):
            monkeypatch.delenv(name)
    env_file = tmp_path / "simulator.env"
    env_file.write_text("MQTT_SIMULATOR_PASSWORD=file-password\n", encoding="utf-8")
    monkeypatch.setenv("MQTT_SIMULATOR_PASSWORD", "environment-password")
    monkeypatch.setenv("SIMULATOR_TELEMETRY_QUEUE_PATH", str(tmp_path / "queue.sqlite3"))
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

    class Publisher:
        count = 0
        closed = False
        session = None
        responses = []

        def connect(self):
            self.session = 1

        def request_allocations(self, session):
            query = AllocationQuery(uuid4(), session)
            query.response = AllocationResponse(
                request_id=query.request_id,
                vials=[ActiveVial(vial_id=1, experiment_id=41, allocation_id=UUID(int=41))],
            )
            query.finished.set()
            return query

        def cancel_query(self, _query):
            pass

        def pump_is_on(self, _allocation):
            return False

        def publish(self, payload, *, session, live):
            event = TelemetryEvent.model_validate_json(payload)
            self.responses.append(TelemetryAcknowledgement(
                schema_version="1.0", event_id=event.event_id, equipment_id=event.equipment_id,
                status="persisted", acknowledged_at=datetime.now(UTC),
            ))
            self.count += 1
            if self.count == 45:
                signal.raise_signal(stop_signal)
            return None

        def outcomes(self):
            responses, self.responses = self.responses, []
            return iter(responses)

        def close(self):
            self.closed = True

    publisher = Publisher()

    def make_runner(settings):
        assert settings.mqtt_simulator_password == "environment-password"
        return SimulatorRunner(settings, publisher=publisher)

    monkeypatch.setattr(cli, "SimulatorRunner", make_runner)
    monkeypatch.setattr("evolver_simulator.runner.ROUND_INTERVAL_SECONDS", 0.025)
    # The fallback limit prevents a broken signal handler from hanging the test.
    assert cli.main(["--env-file", str(env_file), "--max-messages", "60"]) == 0
    assert publisher.count == 45
    assert publisher.closed
    assert {s: signal.getsignal(s) for s in previous} == previous
