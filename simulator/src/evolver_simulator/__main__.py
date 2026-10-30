"""Ponto de entrada para ``python -m evolver_simulator``."""

from __future__ import annotations

import argparse
import logging
import signal
from collections.abc import Sequence

from pydantic import ValidationError

from .config import SimulatorSettings
from .mqtt import MqttConnectionError, MqttPublishError
from .runner import SimulatedFailureError, SimulatorRunner

LOGGER = logging.getLogger(__name__)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publica medicoes simuladas de OD via MQTT 5")
    parser.add_argument(
        "--max-messages",
        type=positive_int,
        help="encerra apos N mensagens; substitui SIMULATOR_MAX_MESSAGES",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        settings = SimulatorSettings()
    except ValidationError as exc:
        LOGGER.error("Configuracao invalida: %s", exc)
        return 2

    runner = SimulatorRunner(settings)

    def request_stop(signum: int, _frame: object) -> None:
        LOGGER.info("Sinal %s recebido; encerrando de forma limpa", signum)
        runner.stop()

    previous_handlers: dict[signal.Signals, signal.Handlers] = {}
    for current_signal in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[current_signal] = signal.signal(current_signal, request_stop)

    try:
        runner.run(max_messages=args.max_messages)
    except SimulatedFailureError as exc:
        LOGGER.error("Cenario de falha simulada concluido: %s", exc)
        return 3
    except (MqttConnectionError, MqttPublishError) as exc:
        LOGGER.error("Falha no transporte MQTT: %s", exc)
        return 1
    finally:
        for current_signal, previous_handler in previous_handlers.items():
            signal.signal(current_signal, previous_handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
