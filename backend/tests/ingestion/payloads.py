"""Telemetry payload builders shared by the ingestion tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

EQUIPMENT_ID = "evolver-sim-01"
TELEMETRY_TOPIC = f"evolver/v1/{EQUIPMENT_ID}/telemetry"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def telemetry(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "event_id": str(uuid4()),
        "producer_id": "simulator-local-01",
        "equipment_id": EQUIPMENT_ID,
        "vial_id": "vial-01",
        "measurement_type": "od",
        "value": 0.42,
        "generated_at": NOW.isoformat(),
        "sequence": 1,
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not ...}


def encode(payload: dict[str, Any] | str) -> bytes:
    return (payload if isinstance(payload, str) else json.dumps(payload)).encode()
