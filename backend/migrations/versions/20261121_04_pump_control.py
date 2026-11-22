"""Persist simulated pump control and command history."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_04"
down_revision = "20261121_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("od_readings", sa.Column("producer_id", sa.String(64)))
    op.add_column("od_readings", sa.Column("sequence", sa.BigInteger()))
    op.create_table(
        "pump_control",
        sa.Column("experiment_id", sa.BigInteger(), sa.ForeignKey("experiments.id"), primary_key=True),
        sa.Column("vial_id", sa.BigInteger(), sa.ForeignKey("vials.vial_id"), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("delete_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmed_state", sa.String(16), nullable=False),
        sa.Column("desired_state", sa.String(16), nullable=False),
        sa.Column("last_generated_at", sa.DateTime(timezone=True)),
        sa.Column("last_producer_id", sa.String(64)),
        sa.Column("last_sequence", sa.BigInteger()),
        sa.Column("pending_command_id", sa.Uuid()),
    )
    op.create_table(
        "pump_commands",
        sa.Column("command_id", sa.Uuid(), primary_key=True),
        sa.Column("experiment_id", sa.BigInteger(), sa.ForeignKey("experiments.id"), nullable=False),
        sa.Column("vial_id", sa.BigInteger(), sa.ForeignKey("vials.vial_id"), nullable=False),
        sa.Column("reading_event_id", sa.Uuid()),
        sa.Column("reading_generated_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("desired_state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("puback_at", sa.DateTime(timezone=True)),
        sa.Column("result_status", sa.String(16), nullable=False),
        sa.Column("result_at", sa.DateTime(timezone=True)),
        sa.Column("result_detail", sa.Text()),
    )
    op.create_index("ix_pump_commands_experiment", "pump_commands", ["experiment_id", "created_at"])
    op.execute("""
        INSERT INTO pump_control (experiment_id, vial_id, paused, confirmed_state, desired_state)
        SELECT id, vial_id, false, 'unknown', 'off' FROM experiments
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrading would discard pump command history; restore a backup")
