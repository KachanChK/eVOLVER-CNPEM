"""Store simulated pH and optical density alongside temperature."""

from alembic import op

revision = "20261111_02"
down_revision = "20261111_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE other_readings (
            event_id uuid NOT NULL,
            generated_at timestamptz NOT NULL,
            received_at timestamptz NOT NULL,
            vial_id bigint NOT NULL REFERENCES vials(vial_id) ON DELETE RESTRICT,
            experiment_id bigint NOT NULL REFERENCES experiments(id) ON DELETE RESTRICT,
            measurement_type varchar(2) NOT NULL CHECK (measurement_type IN ('ph', 'od')),
            value double precision NOT NULL,
            PRIMARY KEY (event_id, generated_at)
        );
        SELECT create_hypertable('other_readings', 'generated_at');
        CREATE INDEX ix_other_readings_experiment_type_time
            ON other_readings (experiment_id, measurement_type, generated_at);
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrading would discard pH and OD history; restore a backup")
