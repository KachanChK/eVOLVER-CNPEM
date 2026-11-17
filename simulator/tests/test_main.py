from __future__ import annotations

import os
import signal
from pathlib import Path

import pytest
from evolver_contracts.pilot import ActiveVial
from evolver_simulator import __main__ as cli
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
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

    class Publisher:
        count = 0
        closed = False

        def connect(self):
            pass

        def active_vials(self):
            return [ActiveVial(vial_id=1, experiment_id=41)]

        def publish(self, event):
            self.count += 1
            if self.count == 45:
                signal.raise_signal(stop_signal)

        def close(self):
            self.closed = True

    publisher = Publisher()

    def make_runner(settings):
        assert settings.mqtt_simulator_password == "environment-password"
        return SimulatorRunner(settings, publisher=publisher)

    monkeypatch.setattr(cli, "SimulatorRunner", make_runner)
    monkeypatch.setattr("evolver_simulator.runner.ROUND_INTERVAL_SECONDS", 0.0)
    # The fallback limit prevents a broken signal handler from hanging the test.
    assert cli.main(["--env-file", str(env_file), "--max-messages", "60"]) == 0
    assert publisher.count == 45
    assert publisher.closed
    assert {s: signal.getsignal(s) for s in previous} == previous
