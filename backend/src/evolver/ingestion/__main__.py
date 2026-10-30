"""Entry point: `uv run --package evolver-cnpem-backend python -m evolver.ingestion`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from evolver.ingestion.config import IngestionSettings
from evolver.ingestion.persistence import TelemetryStore
from evolver.ingestion.service import run


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = IngestionSettings.from_env()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    store = TelemetryStore(sessionmaker(engine))
    # O ProactorEventLoop padrão do Windows não tem add_reader, exigido pelo aiomqtt.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(run(settings, store), loop_factory=loop_factory)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
