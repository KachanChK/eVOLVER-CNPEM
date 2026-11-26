"""Persist telemetry and correlate the application outcome with its producer."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from uuid import UUID

from evolver_contracts.models import (
    TelemetryAcknowledgement,
    TelemetryEvent,
    TelemetryRejection,
)
from evolver_contracts.pilot import EQUIPMENT_ID, TELEMETRY_MODE_PROPERTY
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from .alerts import FRESH_FOR, monitor_reading
from .control import consider_od

TELEMETRY_TOPIC = re.compile(r"evolver/v1/([A-Za-z0-9][A-Za-z0-9._-]{0,63})/telemetry")
READINGS = {
    "temperature": ("temperature_readings", "temperature_celsius"),
    "ph": ("ph_readings", "ph_value"),
    "od": ("od_readings", "od_value"),
}


class PermanentRejection(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class FutureReading(ValueError):
    pass


def payload_hash(message: TelemetryEvent, generated_at: datetime) -> bytes:
    fields = message.model_dump(mode="json")
    fields["generated_at"] = generated_at.isoformat()
    if message.value == 0:
        fields["value"] = 0.0
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).digest()


def matches_legacy(connection: Connection, params: dict, table: str, value_column: str) -> bool:
    is_od = table == "od_readings"
    od_fields = ", r.producer_id, r.sequence, r.allocation_verified" if is_od else ""
    row = connection.execute(text(f"""
        SELECT r.vial_id, r.experiment_id, r.{value_column} AS value,
               v.equipment_id, e.allocation_id {od_fields}
        FROM {table} r JOIN vials v ON v.vial_id = r.vial_id
        JOIN experiments e ON e.id = r.experiment_id
        WHERE r.event_id = :event_id AND r.generated_at = :generated_at
    """), params).mappings().one_or_none()
    fields = ("vial_id", "equipment_id", "value")
    if row is None or any(row[field] != params[field] for field in fields):
        return False
    if params["expected_experiment_id"] not in (None, row.experiment_id):
        return False
    if params["allocation_id"] not in (None, row.allocation_id):
        return False
    if is_od:
        return (
            row.producer_id in (None, params["producer_id"])
            and row.sequence in (None, params["sequence"])
            and (not row.allocation_verified or params["allocation_verified"])
        )
    return True


def store_v1_message(
    engine: Engine, topic: str, payload: bytes, *, live: bool = True, control_ready: bool = True,
) -> str:
    """The caller can acknowledge the result once the transaction has committed."""
    origin = TELEMETRY_TOPIC.fullmatch(topic)
    if origin is None:
        raise PermanentRejection("invalid_origin", "tópico de telemetria inválido")
    try:
        message = TelemetryEvent.model_validate_json(payload)
    except ValidationError as exc:
        version_error = next(
            (error for error in exc.errors() if error["loc"] == ("schema_version",)), None,
        )
        code = (
            "unsupported_schema_version"
            if version_error and version_error["type"] == "literal_error" else "schema_invalid"
        )
        raise PermanentRejection(code, "payload incompatível com a telemetria v1") from exc
    if origin[1] != EQUIPMENT_ID:
        raise PermanentRejection("unknown_equipment", "equipamento do tópico não cadastrado")
    if message.equipment_id != origin[1]:
        raise PermanentRejection("invalid_origin", "equipamento não corresponde ao tópico")
    if not message.vial_id.isascii() or not message.vial_id.isdecimal():
        raise PermanentRejection("unknown_vial", "vial inválido")
    vial_id = int(message.vial_id)
    if not 1 <= vial_id <= 12:
        raise PermanentRejection("unknown_vial", "vial não cadastrado")
    is_od = message.measurement_type == "od"
    if not math.isfinite(message.value) or (is_od and message.sequence > 2**63 - 1):
        raise PermanentRejection("schema_invalid", "valor ou sequência fora da representação")
    run_id = message.experiment_run_id
    experiment_id = allocation_id = None
    if run_id is not None:
        try:
            if run_id.isascii() and run_id.isdecimal():
                experiment_id = int(run_id)
                if not 1 <= experiment_id <= 2**63 - 1:
                    raise ValueError("ID fora do intervalo")
            else:
                allocation_id = UUID(run_id)
        except ValueError as exc:
            raise PermanentRejection(
                "invalid_origin", "identificador de alocação inválido",
            ) from exc
    try:
        generated_at = message.generated_at.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise PermanentRejection("schema_invalid", "horário fora da representação") from exc
    params = {
        "vial_id": vial_id,
        "equipment_id": message.equipment_id,
        "generated_at": generated_at,
        "event_id": message.event_id,
        "value": message.value,
        "measurement_type": message.measurement_type,
        "producer_id": message.producer_id,
        "sequence": message.sequence,
        "expected_experiment_id": experiment_id,
        "allocation_id": allocation_id,
        "allocation_verified": allocation_id is not None,
        "control_eligible": live and control_ready,
        "payload_hash": payload_hash(message, generated_at),
    }
    table, value_column = READINGS[message.measurement_type]
    with engine.begin() as connection:
        received_at = connection.execute(text("""
            INSERT INTO telemetry_events (event_id, generated_at, measurement_type, payload_hash)
            SELECT :event_id, :generated_at, :measurement_type, :payload_hash
            FROM set_config('synchronous_commit', 'on', true)
            ON CONFLICT (event_id) DO NOTHING
            RETURNING clock_timestamp()
        """), params).scalar_one_or_none()
        if received_at is None:
            existing = connection.execute(text("""
                SELECT measurement_type, generated_at, payload_hash
                FROM telemetry_events WHERE event_id = :event_id
            """), params).one()
            if (
                existing.measurement_type == message.measurement_type
                and existing.generated_at == generated_at
            ):
                if existing.payload_hash is None:
                    if matches_legacy(connection, params, table, value_column):
                        return "duplicada"
                elif existing.payload_hash == params["payload_hash"]:
                    return "duplicada"
            raise PermanentRejection("invalid_origin", "event_id já gravado com conteúdo diferente")
        if generated_at > received_at:
            raise FutureReading("horário de geração ainda está no futuro")
        params["received_at"] = received_at
        columns = f"event_id, generated_at, received_at, vial_id, experiment_id, {value_column}"
        values = ":event_id, :generated_at, :received_at, :vial_id, allocation.id, :value"
        decides_od = is_od and params["allocation_verified"] and params["control_eligible"]
        checks_alert = live and allocation_id is not None and received_at - generated_at < FRESH_FOR
        lock = "UPDATE" if decides_od or checks_alert else "SHARE"
        if is_od:
            columns += ", producer_id, sequence, allocation_verified, control_eligible"
            values += ", :producer_id, :sequence, :allocation_verified, :control_eligible"
        experiment_id = connection.execute(text(f"""
            WITH allocation AS (
                SELECT e.id FROM experiments e JOIN vials v ON v.vial_id = e.vial_id
                WHERE e.vial_id = :vial_id AND v.equipment_id = :equipment_id
                  AND (CAST(:expected_experiment_id AS bigint) IS NULL
                       OR e.id = :expected_experiment_id)
                  AND (CAST(:allocation_id AS uuid) IS NULL OR e.allocation_id = :allocation_id)
                  AND e.started_at <= :generated_at
                  AND (e.ended_at IS NULL OR :generated_at < e.ended_at)
                FOR {lock} OF e
            )
            INSERT INTO {table} ({columns}) SELECT {values} FROM allocation
            RETURNING experiment_id
        """), params).scalar_one_or_none()
        if experiment_id is None:
            raise PermanentRejection(
                "invalid_origin", "não havia experimento ativo no horário da leitura",
            )
        params["experiment_id"] = experiment_id
        if checks_alert:
            monitor_reading(connection, params, received_at)
        if decides_od:
            consider_od(connection, params, received_at)
    return "gravada"


def telemetry_is_live(properties) -> bool:
    modes = [
        value for name, value in (getattr(properties, "UserProperty", None) or ())
        if name == TELEMETRY_MODE_PROPERTY
    ]
    return not modes or modes == ["live"]


def correlated_id(payload: bytes) -> UUID | None:
    try:
        return UUID(json.loads(payload)["event_id"])
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return None


def telemetry_outcome(engine: Engine, message, *, control_ready: bool) -> tuple[str, str] | None:
    origin = TELEMETRY_TOPIC.fullmatch(message.topic)
    if origin is None or message.retain:
        return
    try:
        status = store_v1_message(
            engine, message.topic, message.payload,
            live=telemetry_is_live(message.properties), control_ready=control_ready,
        )
    except PermanentRejection as exc:
        event_id = correlated_id(message.payload)
        print(f"Telemetria rejeitada: {message.topic} event_id={event_id} {exc}", flush=True)
        if event_id is not None:
            rejection = TelemetryRejection(
                schema_version="1.0", event_id=event_id, equipment_id=origin[1],
                reason_code=exc.code, detail=str(exc), disposition="quarantined",
                rejected_at=datetime.now(UTC),
            )
            return f"{message.topic}/rejection", rejection.model_dump_json()
        return None
    event_id = correlated_id(message.payload)
    ack = TelemetryAcknowledgement(
        schema_version="1.0", event_id=event_id, equipment_id=origin[1],
        status="persisted" if status == "gravada" else "duplicate",
        acknowledged_at=datetime.now(UTC),
    )
    return f"{message.topic}/ack", ack.model_dump_json()
