"""Add explicit OD limits to experiments."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_02"
down_revision = "20261121_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experiments", sa.Column("od_min", sa.Float(precision=53), nullable=True))
    op.add_column("experiments", sa.Column("od_max", sa.Float(precision=53), nullable=True))
    op.create_check_constraint(
        "ck_experiment_od_limits",
        "experiments",
        "(od_min IS NULL AND od_max IS NULL) OR "
        "(od_min IS NOT NULL AND od_max IS NOT NULL "
        "AND od_min >= 0.10 AND od_max <= 0.80 AND od_min < od_max)",
    )


def downgrade() -> None:
    raise RuntimeError("Downgrading would discard experiment OD limits; restore a backup")
