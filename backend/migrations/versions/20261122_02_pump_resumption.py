"""Persist the accepted OD event and resumption during a pending safe-off."""

import sqlalchemy as sa
from alembic import op

revision = "20261122_02"
down_revision = "20261122_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pump_control", sa.Column("last_event_id", sa.Uuid()))
    op.add_column(
        "pump_control",
        sa.Column("resume_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("""
        UPDATE pump_control c SET last_event_id = (
            SELECT od.event_id FROM od_readings od
            WHERE od.experiment_id = c.experiment_id AND od.vial_id = c.vial_id
              AND od.generated_at = c.last_generated_at AND od.producer_id = c.last_producer_id
              AND od.sequence = c.last_sequence AND od.od_value BETWEEN 0.10 AND 0.80
            ORDER BY od.received_at, od.event_id LIMIT 1
        ) WHERE c.last_generated_at IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_column("pump_control", "resume_pending")
    op.drop_column("pump_control", "last_event_id")
