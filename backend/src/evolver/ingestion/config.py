"""Ingestion settings read from the same environment variables as `.env.example`."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from evolver.db.connection import database_url_from_env

TELEMETRY_SUBSCRIPTION = "evolver/v1/+/telemetry"


@dataclass(frozen=True)
class IngestionSettings:
    database_url: str
    mqtt_password: str
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str = "evolver-ingestion"
    mqtt_client_id: str = "evolver-ingestion"
    # Mantém a sessão no broker para receber o que chegar enquanto a ingestão reinicia.
    mqtt_session_expiry_seconds: int = 3600
    reconnect_interval_seconds: float = 5.0
    # Tolerância para relógios dessincronizados. Um evento além disso viria "do futuro"
    # e ocuparia a leitura atual até o relógio alcançá-lo.
    max_clock_skew: timedelta = timedelta(minutes=5)

    @classmethod
    def from_env(cls) -> IngestionSettings:
        password = os.getenv("MQTT_INGESTION_PASSWORD")
        if not password:
            raise RuntimeError("defina MQTT_INGESTION_PASSWORD (veja .env.example)")
        return cls(
            database_url=database_url_from_env(),
            mqtt_password=password,
            mqtt_host=os.getenv("MQTT_HOST", "127.0.0.1"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            mqtt_username=os.getenv("MQTT_INGESTION_USERNAME", "evolver-ingestion"),
            mqtt_client_id=os.getenv("MQTT_INGESTION_CLIENT_ID", "evolver-ingestion"),
            mqtt_session_expiry_seconds=int(
                os.getenv("MQTT_INGESTION_SESSION_EXPIRY_SECONDS", "3600")
            ),
            max_clock_skew=timedelta(
                seconds=float(os.getenv("INGESTION_MAX_CLOCK_SKEW_SECONDS", "300"))
            ),
        )
