"""Minimal registration of the simulated equipment until metadata CRUD exists (E3 · T10).

Run from the repository root after `alembic upgrade head`:

    uv run --package evolver-cnpem-backend python -m evolver.db.seed

The command is idempotent: existing equipment, positions or enabled vials are kept.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from evolver.db.connection import database_url_from_env
from evolver.db.models import Equipment, Position

DEFAULT_EQUIPMENT_ID = "evolver-sim-01"
DEFAULT_VIAL_IDS = ("vial-01",)


def position_uuid(equipment_id: str, position_code: str) -> UUID:
    """Stable id, so reseeding another database yields the same references."""
    return uuid5(NAMESPACE_URL, f"evolver:{equipment_id}/{position_code}")


def seed_simulated_equipment(
    session: Session,
    *,
    equipment_id: str = DEFAULT_EQUIPMENT_ID,
    vial_ids: Sequence[str] = DEFAULT_VIAL_IDS,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    session.execute(
        insert(Equipment)
        .values(id=equipment_id, name="Equipamento simulado", created_at=now)
        .on_conflict_do_nothing()
    )
    for index, vial_id in enumerate(vial_ids, start=1):
        position_code = f"P{index:02d}"
        session.execute(
            insert(Position)
            .values(
                id=position_uuid(equipment_id, position_code),
                equipment_id=equipment_id,
                position_code=position_code,
                vial_id=vial_id,
                created_at=now,
            )
            .on_conflict_do_nothing()
        )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--equipment-id", default=DEFAULT_EQUIPMENT_ID)
    parser.add_argument("--vial", dest="vial_ids", action="append", metavar="VIAL_ID")
    args = parser.parse_args(argv)

    vial_ids = args.vial_ids or list(DEFAULT_VIAL_IDS)
    engine = create_engine(database_url_from_env())
    with sessionmaker(engine).begin() as session:
        seed_simulated_equipment(session, equipment_id=args.equipment_id, vial_ids=vial_ids)
    engine.dispose()
    print(f"{args.equipment_id}: vials {', '.join(vial_ids)} disponíveis")


if __name__ == "__main__":
    main()
