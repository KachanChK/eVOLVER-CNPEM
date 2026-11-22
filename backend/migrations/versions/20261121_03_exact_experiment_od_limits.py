"""Preserve experiment OD limits as exact decimals."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_03"
down_revision = "20261121_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use PostgreSQL's shortest round-trip text for limits already stored as floats.
    op.execute("SET LOCAL extra_float_digits = 3")
    op.drop_constraint("ck_experiment_od_limits", "experiments", type_="check")
    for name in ("od_min", "od_max"):
        op.alter_column(
            "experiments",
            name,
            existing_type=sa.Float(precision=53),
            type_=sa.Numeric(),
            postgresql_using=f"{name}::text::numeric",
        )
    op.create_check_constraint(
        "ck_experiment_od_limits",
        "experiments",
        "(od_min IS NULL AND od_max IS NULL) OR "
        "(od_min IS NOT NULL AND od_max IS NOT NULL "
        "AND od_min >= 0.10 AND od_max <= 0.80 AND od_min < od_max)",
    )


def downgrade() -> None:
    raise RuntimeError("Downgrading would round exact experiment OD limits; restore a backup")
