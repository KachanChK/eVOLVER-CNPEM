"""Minimal registration of the simulated equipment until metadata CRUD exists (E3 · T10).

Run from the repository root after `alembic upgrade head`:

    uv run --package evolver-cnpem-backend python -m evolver.db.seed --vial vial-02

The command is idempotent and incremental: existing equipment and positions are kept,
a vial already enabled on the equipment is reported as present, and each new vial
takes the first free position code (P01, P02, ...). A vial enabled on another
equipment is a conflict: it is reported, not registered, and the exit code is 1.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from evolver.db.connection import database_url_from_env
from evolver.db.models import Equipment, Position

DEFAULT_EQUIPMENT_ID = "evolver-sim-01"
DEFAULT_VIAL_IDS = ("vial-01",)


@dataclass
class SeedResult:
    """Position code of each requested vial, split by what the run did."""

    added: dict[str, str] = field(default_factory=dict)
    existing: dict[str, str] = field(default_factory=dict)
    conflicts: dict[str, str] = field(default_factory=dict)


def position_uuid(equipment_id: str, position_code: str) -> UUID:
    """Stable id, so reseeding another database yields the same references."""
    return uuid5(NAMESPACE_URL, f"evolver:{equipment_id}/{position_code}")


def seed_simulated_equipment(
    session: Session,
    *,
    equipment_id: str = DEFAULT_EQUIPMENT_ID,
    vial_ids: Sequence[str] = DEFAULT_VIAL_IDS,
    now: datetime | None = None,
) -> SeedResult:
    now = now or datetime.now(UTC)
    result = SeedResult()
    session.execute(
        insert(Equipment)
        .values(id=equipment_id, name="Equipamento simulado", created_at=now)
        .on_conflict_do_nothing()
    )
    # Códigos de posições desabilitadas continuam ocupados: o histórico aponta para elas.
    used_codes = set(
        session.scalars(select(Position.position_code).where(Position.equipment_id == equipment_id))
    )
    for vial_id in dict.fromkeys(vial_ids):
        enabled = session.execute(
            select(Position.equipment_id, Position.position_code).where(
                Position.vial_id == vial_id, Position.enabled
            )
        ).first()
        if enabled is not None:
            if enabled.equipment_id == equipment_id:
                result.existing[vial_id] = enabled.position_code
            else:
                result.conflicts[vial_id] = (
                    f"habilitado em {enabled.equipment_id}/{enabled.position_code}"
                )
            continue

        position_code = _first_free_code(used_codes)
        inserted = session.execute(
            insert(Position)
            .values(
                id=position_uuid(equipment_id, position_code),
                equipment_id=equipment_id,
                position_code=position_code,
                vial_id=vial_id,
                created_at=now,
            )
            .on_conflict_do_nothing()
            .returning(Position.id)
        ).first()
        used_codes.add(position_code)
        if inserted is None:
            # Só acontece com cadastro concorrente ou id já usado por outro código.
            result.conflicts[vial_id] = f"posição {position_code} não pôde ser criada"
        else:
            result.added[vial_id] = position_code
    return result


def _first_free_code(used_codes: set[str]) -> str:
    number = 1
    while f"P{number:02d}" in used_codes:
        number += 1
    return f"P{number:02d}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--equipment-id", default=DEFAULT_EQUIPMENT_ID)
    parser.add_argument("--vial", dest="vial_ids", action="append", metavar="VIAL_ID")
    args = parser.parse_args(argv)

    engine = create_engine(database_url_from_env())
    try:
        with sessionmaker(engine).begin() as session:
            result = seed_simulated_equipment(
                session,
                equipment_id=args.equipment_id,
                vial_ids=args.vial_ids or DEFAULT_VIAL_IDS,
            )
    finally:
        engine.dispose()

    for vial_id, code in result.added.items():
        print(f"{args.equipment_id}: {vial_id} cadastrado em {code}")
    for vial_id, code in result.existing.items():
        print(f"{args.equipment_id}: {vial_id} já estava em {code}")
    for vial_id, reason in result.conflicts.items():
        print(f"{args.equipment_id}: {vial_id} NÃO cadastrado ({reason})", file=sys.stderr)
    return 1 if result.conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
