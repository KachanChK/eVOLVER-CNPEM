"""Reserve telemetry IDs across all three hypertables."""

import sqlalchemy as sa
from alembic import op

revision = "20261123_02"
down_revision = "20261123_01"
branch_labels = None
depends_on = None

READINGS = """
    SELECT event_id, generated_at, 'temperature' AS measurement_type FROM temperature_readings
    UNION ALL SELECT event_id, generated_at, 'ph' FROM ph_readings
    UNION ALL SELECT event_id, generated_at, 'od' FROM od_readings
"""


def upgrade() -> None:
    op.execute("LOCK TABLE temperature_readings, ph_readings, od_readings IN SHARE MODE")
    op.execute(f"""
        DO $$
        DECLARE conflicts text;
        BEGIN
            SELECT string_agg(event_id::text, ', ' ORDER BY event_id) INTO conflicts
            FROM (
                SELECT event_id FROM ({READINGS}) AS readings GROUP BY event_id
                HAVING count(*) > 1
            ) AS duplicates;
            IF conflicts IS NOT NULL THEN
                RAISE EXCEPTION 'UUIDs de telemetria em conflito: %', conflicts;
            END IF;
        END
        $$;
    """)
    op.create_table(
        "telemetry_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("measurement_type", sa.String(11), nullable=False),
        sa.Column("payload_hash", sa.LargeBinary(32)),
    )
    op.execute(f"""
        INSERT INTO telemetry_events (event_id, generated_at, measurement_type) {READINGS}
    """)
    op.add_column("od_readings", sa.Column(
        "control_eligible", sa.Boolean(), nullable=False, server_default=sa.true(),
    ))


def downgrade() -> None:
    op.drop_column("od_readings", "control_eligible")
    op.drop_table("telemetry_events")
