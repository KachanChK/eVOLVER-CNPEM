from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from evolver.db.models import Position
from evolver.db.seed import main

pytestmark = pytest.mark.integration


@pytest.fixture
def seed(database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """Run the seed CLI against the disposable database and return (exit, stdout, stderr)."""
    monkeypatch.setenv("DATABASE_URL", database_url)

    def run(*argv: str) -> tuple[int, str, str]:
        code = main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run


def positions(session_factory: sessionmaker[Session], equipment_id: str) -> dict[str, str]:
    with session_factory() as session:
        rows = session.execute(
            select(Position.vial_id, Position.position_code).where(
                Position.equipment_id == equipment_id, Position.enabled
            )
        )
        return dict(rows.all())


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def test_successive_runs_add_vials_to_free_positions(
    seed, session_factory: sessionmaker[Session]
) -> None:
    equipment_id, vial_1, vial_2 = unique("test"), unique("vial"), unique("vial")

    first = seed("--equipment-id", equipment_id, "--vial", vial_1)
    second = seed("--equipment-id", equipment_id, "--vial", vial_2)

    assert first == (0, f"{equipment_id}: {vial_1} cadastrado em P01\n", "")
    assert second == (0, f"{equipment_id}: {vial_2} cadastrado em P02\n", "")
    assert positions(session_factory, equipment_id) == {vial_1: "P01", vial_2: "P02"}


def test_repeated_run_is_idempotent(seed, session_factory: sessionmaker[Session]) -> None:
    equipment_id, vial_1, vial_2 = unique("test"), unique("vial"), unique("vial")
    seed("--equipment-id", equipment_id, "--vial", vial_1, "--vial", vial_2)

    code, out, err = seed("--equipment-id", equipment_id, "--vial", vial_1, "--vial", vial_2)

    assert code == 0
    assert err == ""
    assert out == (
        f"{equipment_id}: {vial_1} já estava em P01\n"
        f"{equipment_id}: {vial_2} já estava em P02\n"
    )
    assert positions(session_factory, equipment_id) == {vial_1: "P01", vial_2: "P02"}


def test_vial_enabled_elsewhere_is_reported_and_not_announced(
    seed, session_factory: sessionmaker[Session]
) -> None:
    owner, other, vial, free_vial = unique("test"), unique("test"), unique("vial"), unique("vial")
    seed("--equipment-id", owner, "--vial", vial)

    code, out, err = seed("--equipment-id", other, "--vial", vial, "--vial", free_vial)

    assert code == 1
    assert out == f"{other}: {free_vial} cadastrado em P01\n"
    assert err == f"{other}: {vial} NÃO cadastrado (habilitado em {owner}/P01)\n"
    assert positions(session_factory, owner) == {vial: "P01"}
    assert positions(session_factory, other) == {free_vial: "P01"}


def test_code_of_disabled_position_stays_reserved(
    seed, session_factory: sessionmaker[Session]
) -> None:
    equipment_id, old_vial, new_vial = unique("test"), unique("vial"), unique("vial")
    seed("--equipment-id", equipment_id, "--vial", old_vial)
    with session_factory.begin() as session:
        session.execute(
            update(Position).where(Position.vial_id == old_vial).values(enabled=False)
        )

    code, out, _ = seed("--equipment-id", equipment_id, "--vial", new_vial)

    assert code == 0
    assert out == f"{equipment_id}: {new_vial} cadastrado em P02\n"
