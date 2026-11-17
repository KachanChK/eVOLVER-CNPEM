"""Ponto de entrada para ``python -m evolver_simulator``."""

from __future__ import annotations

import argparse
import logging
import signal
from collections.abc import Sequence
from pathlib import Path

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
    parser = argparse.ArgumentParser(
        description="Simula OD, pH e temperatura continuamente; pressione Ctrl+C para parar",
    )
    parser.add_argument(
        "--max-messages",
        type=positive_int,
        help="encerra apos este total de medicoes; por padrao, executa sem limite",
    )
    parser.add_argument("--env-file", type=Path, help="arquivo de configuracao do simulador")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        settings = (
            SimulatorSettings(_env_file=args.env_file)
            if args.env_file is not None
            else SimulatorSettings()
        )
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
        LOGGER.info("Simulacao iniciada. Pressione Ctrl+C para parar.")
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
