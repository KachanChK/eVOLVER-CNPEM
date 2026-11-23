"""Assign a durable identity to each experiment allocation."""

import sqlalchemy as sa
from alembic import op

revision = "20261122_03"
down_revision = "20261122_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "experiments",
        sa.Column("allocation_id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"),
                  nullable=False),
    )
    op.create_unique_constraint("uq_experiments_allocation_id", "experiments", ["allocation_id"])


def downgrade() -> None:
    op.drop_constraint("uq_experiments_allocation_id", "experiments", type_="unique")
    op.drop_column("experiments", "allocation_id")
