"""Keep historical OD distinct from readings tied to an allocation."""

import sqlalchemy as sa
from alembic import op

revision = "20261122_04"
down_revision = "20261122_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "od_readings",
        sa.Column("allocation_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("od_readings", "allocation_verified")
