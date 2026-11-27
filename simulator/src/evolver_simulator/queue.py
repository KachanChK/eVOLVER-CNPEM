"""Durable producer outbox and last confirmed vial allocation."""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime

from evolver_contracts.models import TelemetryAcknowledgement, TelemetryEvent, TelemetryRejection
from evolver_contracts.pilot import AllocationResponse

from .config import SimulatorSettings


class QueueIdentityError(ValueError):
    pass


class TelemetryQueue:
    def __init__(self, settings: SimulatorSettings) -> None:
        path = settings.telemetry_queue_path
        path.parent.mkdir(parents=True, exist_ok=True)
        database = sqlite3.connect(path, timeout=0.1)
        database.row_factory = sqlite3.Row
        self.database = database
        self.identity = (settings.equipment_id, settings.producer_id)
        self.capacity = settings.telemetry_queue_max_events
        self._count_version = None
        self._event_count = 0
        try:
            if database.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise sqlite3.OperationalError("não foi possível habilitar WAL na fila")
            database.execute("PRAGMA synchronous=FULL")
            database.executescript("""
                CREATE TABLE IF NOT EXISTS queue_metadata (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    equipment_id TEXT NOT NULL,
                    producer_id TEXT NOT NULL,
                    allocation_response TEXT
                );
                CREATE TABLE IF NOT EXISTS telemetry_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    generated_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    rejected_at TEXT,
                    reason_code TEXT,
                    detail TEXT
                );
                CREATE INDEX IF NOT EXISTS pending_telemetry ON telemetry_queue (id)
                    WHERE rejected_at IS NULL;
                CREATE INDEX IF NOT EXISTS pending_generation ON telemetry_queue (generated_at)
                    WHERE rejected_at IS NULL;
            """)
            with database:
                database.execute(
                    "INSERT OR IGNORE INTO queue_metadata VALUES (1, ?, ?, NULL)", self.identity,
                )
                identity = database.execute("""
                    SELECT equipment_id, producer_id FROM queue_metadata WHERE id = 1
                """).fetchone()
                if tuple(identity) != self.identity:
                    raise QueueIdentityError(
                        f"fila pertence a {tuple(identity)}, configuração usa {self.identity}",
                    )
            # Delivery timing is process-local, so a restart makes all pending rows historical.
            database.execute("PRAGMA temp_store=MEMORY")
            database.execute("""
                CREATE TEMP TABLE delivery (
                    id INTEGER PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0,
                    eligible_at REAL NOT NULL DEFAULT 0, live_until REAL, session INTEGER,
                    held_until REAL
                )
            """)
            database.execute("CREATE INDEX delivery_live ON delivery (session, live_until, id)")
        except BaseException:
            database.close()
            raise

    def close(self) -> None:
        self.database.close()

    def last_allocation(self) -> AllocationResponse | None:
        cached = self.database.execute(
            "SELECT allocation_response FROM queue_metadata WHERE id = 1",
        ).fetchone()[0]
        return AllocationResponse.model_validate_json(cached) if cached is not None else None

    def confirm_allocation(self, response: AllocationResponse) -> None:
        with self.database:
            self.database.execute(
                "UPDATE queue_metadata SET allocation_response = ? WHERE id = 1",
                (response.model_dump_json(),),
            )

    def has_room(self, size: int) -> bool:
        version = self.database.execute("PRAGMA data_version").fetchone()[0]
        if version != self._count_version:
            self._event_count = self.database.execute(
                "SELECT count(*) FROM telemetry_queue",
            ).fetchone()[0]
            self._count_version = version
        return self._event_count + size <= self.capacity

    def append(
        self, events: list[TelemetryEvent], *, session: int | None, live_until: float,
        hold: tuple[str, float] | None = None,
    ) -> bool:
        with self.database:
            if not self.has_room(len(events)):
                return False
            for event in events:
                identity = event.equipment_id, event.producer_id
                if identity != self.identity or not math.isfinite(event.value):
                    raise ValueError("evento inválido para esta fila")
                row_id = self.database.execute("""
                    INSERT INTO telemetry_queue (event_id, generated_at, payload) VALUES (?, ?, ?)
                """, (
                    str(event.event_id), event.generated_at.astimezone(UTC).isoformat(
                        timespec="microseconds",
                    ), event.model_dump_json(),
                )).lastrowid
                if hold and event.experiment_run_id == hold[0]:
                    self.database.execute(
                        "INSERT INTO delivery (id, held_until) VALUES (?, ?)", (row_id, hold[1]),
                    )
                elif session is not None:
                    self.database.execute(
                        "INSERT INTO delivery (id, live_until, session) VALUES (?, ?, ?)",
                        (row_id, live_until, session),
                    )
        self._event_count += len(events)
        return True

    def release_held(self) -> None:
        with self.database:
            self.database.execute("""
                UPDATE delivery SET held_until = NULL WHERE held_until IS NOT NULL
            """)

    def eligible(
        self, now: float, session: int, limit: int, *, live: bool,
    ) -> list[sqlite3.Row]:
        is_live = "d.session = :session AND d.live_until > :now"
        if live:
            query = f"""
                SELECT q.*, d.attempts, d.live_until
                FROM delivery d JOIN telemetry_queue q USING (id)
                WHERE q.rejected_at IS NULL AND {is_live} ORDER BY q.id LIMIT :limit
            """
        else:
            query = f"""
                SELECT q.*, coalesce(d.attempts, 0) AS attempts
                FROM telemetry_queue q LEFT JOIN delivery d USING (id)
                WHERE q.rejected_at IS NULL AND coalesce(d.eligible_at, 0) <= :now
                  AND (d.held_until IS NULL OR d.held_until <= :now)
                  AND NOT coalesce({is_live}, 0) ORDER BY q.id LIMIT :limit
            """
        params = {"now": now, "session": session, "limit": limit}
        return self.database.execute(query, params).fetchall()

    def schedule(self, row_id: int, attempts: int, eligible_at: float) -> None:
        with self.database:
            self.database.execute("""
                INSERT INTO delivery (id, attempts, eligible_at) VALUES (?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET attempts = excluded.attempts,
                    eligible_at = excluded.eligible_at, live_until = NULL, session = NULL
            """, (row_id, attempts, eligible_at))

    def apply(self, responses: list[TelemetryAcknowledgement | TelemetryRejection]):
        applied = []
        deleted = 0
        with self.database:
            for response in responses:
                if response.equipment_id != self.identity[0]:
                    continue
                row = self.database.execute("""
                    SELECT id FROM telemetry_queue WHERE event_id = ? AND rejected_at IS NULL
                """, (str(response.event_id),)).fetchone()
                if row is None:
                    continue
                row_id = row["id"]
                if isinstance(response, TelemetryRejection):
                    self.quarantine(
                        row_id, response.reason_code, response.detail, response.rejected_at,
                    )
                else:
                    self.database.execute("DELETE FROM telemetry_queue WHERE id = ?", (row_id,))
                    self.database.execute("DELETE FROM delivery WHERE id = ?", (row_id,))
                    deleted += 1
                applied.append((row_id, response))
        self._event_count -= deleted
        return applied

    def quarantine(
        self, row_id: int, reason: str, detail: str | None, rejected_at: datetime,
    ) -> None:
        self.database.execute("""
            UPDATE telemetry_queue SET rejected_at = ?, reason_code = ?, detail = ?
            WHERE id = ? AND rejected_at IS NULL
        """, (rejected_at.isoformat(), reason, detail, row_id))
        self.database.execute("DELETE FROM delivery WHERE id = ?", (row_id,))

    def has_pending(self) -> bool:
        return self.database.execute("""
            SELECT 1 FROM telemetry_queue WHERE rejected_at IS NULL LIMIT 1
        """).fetchone() is not None

    def stats(self) -> tuple[int, int, datetime | None]:
        total, pending, oldest = self.database.execute("""
            SELECT (SELECT count(*) FROM telemetry_queue),
                   (SELECT count(*) FROM telemetry_queue WHERE rejected_at IS NULL),
                   (SELECT min(generated_at) FROM telemetry_queue WHERE rejected_at IS NULL)
        """).fetchone()
        try:
            generated_at = datetime.fromisoformat(oldest).astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            generated_at = None
        return pending, total - pending, generated_at

    def validate(self, row: sqlite3.Row) -> None:
        event = TelemetryEvent.model_validate_json(row["payload"])
        generated_at = event.generated_at.astimezone(UTC).isoformat(timespec="microseconds")
        if (
            str(event.event_id) != row["event_id"]
            or (event.equipment_id, event.producer_id) != self.identity
            or generated_at != row["generated_at"]
            or not math.isfinite(event.value)
        ):
            raise ValueError("identidade, valor ou horário divergente no registro da fila")
