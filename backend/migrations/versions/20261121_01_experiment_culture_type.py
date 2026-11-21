"""Add the culture type to experiments."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_01"
down_revision = "20261111_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experiments", sa.Column("culture_type", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Downgrading would discard experiment culture types; restore a backup")
