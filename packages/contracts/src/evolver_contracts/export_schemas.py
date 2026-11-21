"""Gera os JSON Schemas comprometidos com a versão atual dos modelos Pydantic."""

from __future__ import annotations

import json
from pathlib import Path

from .models import schema_sources


def write_schemas(destination: Path | None = None) -> None:
    schema_directory = destination or Path(__file__).with_name("schemas")
    schema_directory.mkdir(parents=True, exist_ok=True)

    for filename, schema in schema_sources().items():
        (schema_directory / filename).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    write_schemas()
