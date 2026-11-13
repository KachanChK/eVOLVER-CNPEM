"""Separate pH and OD readings while preserving their existing history."""

from alembic import op

revision = "20261111_03"
down_revision = "20261111_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Block concurrent inserts until the copy and verification are committed.
    op.execute("LOCK TABLE other_readings IN ACCESS EXCLUSIVE MODE")
    for table, value_column in (("ph_readings", "ph_value"), ("od_readings", "od_value")):
        op.execute(f"""
            CREATE TABLE {table} (
                event_id uuid NOT NULL,
                generated_at timestamptz NOT NULL,
                received_at timestamptz NOT NULL,
                vial_id bigint NOT NULL REFERENCES vials(vial_id) ON DELETE RESTRICT,
                experiment_id bigint NOT NULL REFERENCES experiments(id) ON DELETE RESTRICT,
                {value_column} double precision NOT NULL,
                PRIMARY KEY (event_id, generated_at)
            );
            SELECT create_hypertable('{table}', 'generated_at');
            CREATE INDEX ix_{table}_vial_time ON {table} (vial_id, generated_at);
            CREATE INDEX ix_{table}_experiment_time ON {table} (experiment_id, generated_at);
        """)
    op.execute("""
        INSERT INTO ph_readings
            (event_id, generated_at, received_at, vial_id, experiment_id, ph_value)
        SELECT event_id, generated_at, received_at, vial_id, experiment_id, value
        FROM other_readings WHERE measurement_type = 'ph';

        INSERT INTO od_readings
            (event_id, generated_at, received_at, vial_id, experiment_id, od_value)
        SELECT event_id, generated_at, received_at, vial_id, experiment_id, value
        FROM other_readings WHERE measurement_type = 'od';

        DO $$
        BEGIN
            IF EXISTS (
                (SELECT event_id, generated_at, received_at, vial_id, experiment_id, value
                 FROM other_readings WHERE measurement_type = 'ph'
                 EXCEPT ALL
                 SELECT event_id, generated_at, received_at, vial_id, experiment_id, ph_value
                 FROM ph_readings)
                UNION ALL
                (SELECT event_id, generated_at, received_at, vial_id, experiment_id, value
                 FROM other_readings WHERE measurement_type = 'od'
                 EXCEPT ALL
                 SELECT event_id, generated_at, received_at, vial_id, experiment_id, od_value
                 FROM od_readings)
            ) OR (SELECT count(*) FROM other_readings) !=
                 (SELECT count(*) FROM ph_readings) + (SELECT count(*) FROM od_readings) THEN
                RAISE EXCEPTION 'pH/OD migration verification failed';
            END IF;
        END $$;
        DROP TABLE other_readings;
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrading requires a planned migration; restore a backup")
