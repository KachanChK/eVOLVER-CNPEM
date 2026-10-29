from __future__ import annotations

from sqlalchemy.orm import configure_mappers

from evolver.db.models import Base


def test_every_foreign_key_has_a_relationship() -> None:
    """Sem relationship, o flush pode inserir o filho antes do pai na mesma sessão."""
    configure_mappers()
    missing = []
    for mapper in Base.registry.mappers:
        covered = {
            frozenset(column.name for column in relationship.local_columns)
            for relationship in mapper.relationships
        }
        for constraint in mapper.local_table.foreign_key_constraints:
            columns = frozenset(constraint.column_keys)
            if columns not in covered:
                missing.append(f"{mapper.local_table.name}({', '.join(sorted(columns))})")

    assert missing == []
