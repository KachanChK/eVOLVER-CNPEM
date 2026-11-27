"""Track one safe reconciliation after an uncertain MQTT session."""

import sqlalchemy as sa
from alembic import op

revision = "20261122_01"
down_revision = "20261121_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pump_control",
        sa.Column("reconcile_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("pump_control", "reconcile_required")
