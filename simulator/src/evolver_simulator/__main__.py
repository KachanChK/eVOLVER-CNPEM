"""Ponto de entrada para ``python -m evolver_simulator``."""

from __future__ import annotations

import argparse
import logging
import signal
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from .config import SimulatorSettings
from .mqtt import MqttConnectionError, MqttPublishError
from .queue import QueueIdentityError
from .runner import SimulatedFailureError, SimulatorRunner
from .scenarios import Scenarios
from .test_center import TestCenterError, run_with_center

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
        help="encerra apos gravar este total de medicoes novas e tentar confirmar o envio",
    )
    parser.add_argument("--env-file", type=Path, help="arquivo de configuracao do simulador")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--test-center", dest="test_center", action="store_true",
                      help="abre a Central de testes junto com a coleta")
    mode.add_argument("--headless", dest="test_center", action="store_false",
                      help="executa sem janela (padrão)")
    mode.add_argument("--reset-sqlite", action="store_true",
                      help="apaga o estado das bombas e a fila; pare o simulador antes")
    parser.set_defaults(test_center=False)
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

    if args.reset_sqlite:
        try:
            for database in (settings.pump_state_path, settings.telemetry_queue_path):
                for suffix in ("", "-journal", "-wal", "-shm"):
                    Path(f"{database}{suffix}").unlink(missing_ok=True)
        except OSError as exc:
            LOGGER.error("Falha ao limpar o SQLite. Verifique se o simulador está parado. %s", exc)
            return 1
        LOGGER.info("Estado das bombas e fila de telemetria limpos.")
        return 0

    scenarios = Scenarios() if args.test_center else None
    runner = SimulatorRunner(settings, scenarios=scenarios) if scenarios else SimulatorRunner(
        settings,
    )

    def request_stop(signum: int, _frame: object) -> None:
        LOGGER.info("Sinal %s recebido; encerrando de forma limpa", signum)
        runner.stop()

    previous_handlers: dict[signal.Signals, signal.Handlers] = {}
    for current_signal in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[current_signal] = signal.signal(current_signal, request_stop)

    try:
        LOGGER.info("Simulacao iniciada. Pressione Ctrl+C para parar.")
        if scenarios:
            run_with_center(runner, scenarios, args.max_messages)
        else:
            runner.run(max_messages=args.max_messages)
    except SimulatedFailureError as exc:
        LOGGER.error("Cenario de falha simulada concluido: %s", exc)
        return 3
    except (MqttConnectionError, MqttPublishError) as exc:
        LOGGER.error("Falha no transporte MQTT: %s", exc)
        return 1
    except TestCenterError as exc:
        LOGGER.error("%s", exc)
        return 1
    except (OSError, sqlite3.Error, QueueIdentityError) as exc:
        LOGGER.error("Fila de telemetria indisponível: %s", exc)
        return 1
    finally:
        for current_signal, previous_handler in previous_handlers.items():
            signal.signal(current_signal, previous_handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
