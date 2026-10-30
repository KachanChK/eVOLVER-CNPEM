"""Database URL shared by Alembic, ingestion and local scripts."""

from __future__ import annotations

import os

from sqlalchemy.engine import URL


def database_url_from_env() -> str:
    """Use DATABASE_URL or build the URL from the local Compose defaults."""
    configured_url = os.getenv("DATABASE_URL")
    if configured_url:
        return configured_url
    return URL.create(
        "postgresql+psycopg",
        username=os.getenv("POSTGRES_USER", "evolver"),
        password=os.getenv("POSTGRES_PASSWORD", "evolver-local-only"),
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "evolver"),
    ).render_as_string(hide_password=False)
