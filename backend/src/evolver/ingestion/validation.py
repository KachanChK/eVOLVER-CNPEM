"""Telemetry checks that do not need the database.

Each MQTT message ends in one of three results: accepted for persistence, rejected
with a contract reason (and quarantined), or uncorrelated when not even a valid
`event_id` can be read, so no rejection can be addressed to the producer.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError

from evolver_contracts import TelemetryEvent

type RejectionReason = Literal[
    "schema_invalid",
    "unsupported_schema_version",
    "invalid_origin",
    "unknown_equipment",
    "unknown_vial",
]

SUPPORTED_SCHEMA_VERSION = "1.0"
MAX_DETAIL_LENGTH = 250
# measurements.sequence é BIGINT; acima disso a gravação falharia sem resposta.
MAX_SEQUENCE = 2**63 - 1
# Mesmo formato de Identifier no contrato; outro valor no tópico não pode ser respondido.
_TOPIC_PATTERN = re.compile(
    r"^evolver/v1/(?P<equipment_id>[A-Za-z0-9][A-Za-z0-9._-]{0,63})/telemetry$"
)


@dataclass(frozen=True)
class AcceptedTelemetry:
    topic_equipment_id: str
    event: TelemetryEvent
    raw_payload: str


@dataclass(frozen=True)
class RejectedTelemetry:
    topic_equipment_id: str
    event_id: UUID
    reason_code: RejectionReason
    detail: str | None
    raw_payload: str
    # Presente quando o payload passou pelo contrato e foi rejeitado por outra regra.
    event: TelemetryEvent | None = None


@dataclass(frozen=True)
class UncorrelatedTelemetry:
    topic: str
    detail: str


type ValidationResult = AcceptedTelemetry | RejectedTelemetry | UncorrelatedTelemetry


def equipment_id_from_topic(topic: str) -> str | None:
    match = _TOPIC_PATTERN.match(topic)
    return match.group("equipment_id") if match else None


def short_detail(text: str) -> str:
    """Escape and fit a detail into the contract's 250 characters, never splitting an escape.

    The detail may quote received field names. PostgreSQL rejects NUL in JSONB and
    lone surrogates cannot be encoded, so control characters and surrogates are
    written as `\\uXXXX`, still visible for diagnosis.
    """
    pieces = _escaped_chars(" ".join(text.split()))
    if sum(len(piece) for piece in pieces) <= MAX_DETAIL_LENGTH:
        return "".join(pieces)
    kept: list[str] = []
    length = 0
    for piece in pieces:
        if length + len(piece) > MAX_DETAIL_LENGTH - 3:
            break
        kept.append(piece)
        length += len(piece)
    return "".join(kept) + "..."


def _escaped_chars(text: str) -> list[str]:
    return [
        f"\\u{ord(char):04x}" if unicodedata.category(char) in {"Cc", "Cs"} else char
        for char in text
    ]


def validate_telemetry(
    topic: str,
    payload: bytes,
    *,
    now: datetime,
    max_clock_skew: timedelta,
) -> ValidationResult:
    """Validate one MQTT telemetry message against the contract and origin rules."""
    topic_equipment_id = equipment_id_from_topic(topic)
    if topic_equipment_id is None:
        return UncorrelatedTelemetry(topic, "tópico fora do contrato de telemetria")

    try:
        raw_payload = payload.decode("utf-8")
        # NaN/Infinity viram texto e são recusados pelo modelo estrito, em vez de float.
        data: Any = json.loads(raw_payload, parse_constant=str)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return UncorrelatedTelemetry(topic, short_detail(f"payload não é JSON UTF-8: {error}"))
    # O payload vai para a quarentena em JSONB, que não aceita NUL.
    raw_payload = raw_payload.replace("\x00", "\\u0000")

    event_id = _event_id(data)
    if event_id is None:
        return UncorrelatedTelemetry(topic, "payload sem event_id UUID")

    def reject(
        reason_code: RejectionReason, detail: str, event: TelemetryEvent | None = None
    ) -> RejectedTelemetry:
        return RejectedTelemetry(
            topic_equipment_id=topic_equipment_id,
            event_id=event_id,
            reason_code=reason_code,
            detail=short_detail(detail),
            raw_payload=raw_payload,
            event=event,
        )

    schema_version = data.get("schema_version")
    if schema_version is not None and schema_version != SUPPORTED_SCHEMA_VERSION:
        return reject(
            "unsupported_schema_version",
            f"schema_version {schema_version!r} não suportada; use {SUPPORTED_SCHEMA_VERSION}",
        )

    try:
        # Modo estrito: valor numérico em texto ("0.3") não é convertido silenciosamente.
        event = TelemetryEvent.model_validate_json(json.dumps(data), strict=True)
    except (ValidationError, ValueError) as error:
        return reject("schema_invalid", _validation_detail(error))

    if event.equipment_id != topic_equipment_id:
        return reject(
            "invalid_origin",
            f"equipment_id {event.equipment_id} difere do tópico ({topic_equipment_id})",
            event,
        )
    if not math.isfinite(event.value):
        return reject("schema_invalid", "value deve ser um número finito", event)
    if event.sequence > MAX_SEQUENCE:
        return reject("schema_invalid", f"sequence deve ser no máximo {MAX_SEQUENCE}", event)
    if event.generated_at > now + max_clock_skew:
        return reject(
            "schema_invalid",
            f"generated_at {event.generated_at.isoformat()} está no futuro",
            event,
        )

    return AcceptedTelemetry(topic_equipment_id, event, raw_payload)


def _event_id(data: Any) -> UUID | None:
    if not isinstance(data, dict) or not isinstance(data.get("event_id"), str):
        return None
    try:
        return UUID(data["event_id"])
    except ValueError:
        return None


def _validation_detail(error: ValidationError | ValueError) -> str:
    if not isinstance(error, ValidationError):
        return str(error)
    parts = []
    for item in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"]) or "payload"
        parts.append(f"{location}: {item['msg']}")
    return "; ".join(parts)
