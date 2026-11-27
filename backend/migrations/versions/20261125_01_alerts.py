"""Track alert occurrences and the progress of live telemetry."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261125_01"
down_revision = "20261123_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_monitoring",
        sa.Column("allocation_id", sa.Uuid(), sa.ForeignKey("experiments.allocation_id"),
                  primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("temperature_at", sa.DateTime(timezone=True)),
        sa.Column("ph_at", sa.DateTime(timezone=True)),
        sa.Column("od_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("allocation_id", sa.Uuid(), sa.ForeignKey("experiments.allocation_id"),
                  nullable=False),
        sa.Column("experiment_id", sa.BigInteger(), sa.ForeignKey("experiments.id"),
                  nullable=False),
        sa.Column("experiment_name", sa.String(120), nullable=False),
        sa.Column("vial_id", sa.BigInteger(), sa.ForeignKey("vials.vial_id"), nullable=False),
        sa.Column("type", sa.String(24), nullable=False),
        sa.Column("emitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", JSONB(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "uq_alerts_open", "alerts", ["allocation_id", "type"], unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index(
        "ix_alerts_visible", "alerts", ["emitted_at", "id"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "ix_alerts_unread", "alerts", ["id"],
        postgresql_where=sa.text("archived_at IS NULL AND read_at IS NULL"),
    )
    op.add_column("pump_commands", sa.Column("received_at", sa.DateTime(timezone=True)))
    op.execute("""
        UPDATE pump_commands SET received_at = result_at WHERE result_status = 'received'
    """)


def downgrade() -> None:
    op.drop_column("pump_commands", "received_at")
    op.drop_table("alerts")
    op.drop_table("alert_monitoring")
