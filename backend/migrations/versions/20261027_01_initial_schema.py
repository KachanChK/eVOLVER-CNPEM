"""Create the pilot's metadata, telemetry, command and audit schema."""

from alembic import op

revision = "20261027_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE equipment (
            id varchar(64) PRIMARY KEY,
            name varchar(120),
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL
        );

        CREATE TABLE positions (
            id uuid PRIMARY KEY,
            equipment_id varchar(64) NOT NULL REFERENCES equipment(id) ON DELETE RESTRICT,
            position_code varchar(64) NOT NULL,
            vial_id varchar(64) NOT NULL UNIQUE,
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL,
            CONSTRAINT uq_positions_equipment_code UNIQUE (equipment_id, position_code)
        );

        CREATE TABLE cultures (
            id uuid PRIMARY KEY,
            vial_id varchar(64) NOT NULL UNIQUE,
            organism varchar(120),
            label varchar(120),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL
        );

        CREATE TABLE experiment_runs (
            id varchar(64) PRIMARY KEY,
            equipment_id varchar(64) NOT NULL REFERENCES equipment(id) ON DELETE RESTRICT,
            position_id uuid NOT NULL REFERENCES positions(id) ON DELETE RESTRICT,
            culture_id uuid REFERENCES cultures(id) ON DELETE SET NULL,
            started_at timestamptz NOT NULL,
            ended_at timestamptz,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_run_time_order CHECK (ended_at IS NULL OR ended_at >= started_at)
        );
        CREATE INDEX ix_experiment_runs_position_started
            ON experiment_runs (position_id, started_at DESC);

        CREATE TABLE processed_event_ids (
            event_id uuid PRIMARY KEY,
            equipment_id varchar(64) NOT NULL REFERENCES equipment(id) ON DELETE RESTRICT,
            producer_id varchar(64) NOT NULL,
            generated_at timestamptz NOT NULL,
            received_at timestamptz NOT NULL,
            outcome varchar(16) NOT NULL DEFAULT 'persisted',
            CONSTRAINT ck_processed_event_outcome CHECK (outcome IN ('persisted', 'quarantined'))
        );
        CREATE INDEX ix_processed_event_ids_received_at ON processed_event_ids (received_at DESC);

        CREATE TABLE measurements (
            event_id uuid NOT NULL,
            generated_at timestamptz NOT NULL,
            received_at timestamptz NOT NULL,
            equipment_id varchar(64) NOT NULL REFERENCES equipment(id) ON DELETE RESTRICT,
            position_id uuid NOT NULL REFERENCES positions(id) ON DELETE RESTRICT,
            experiment_run_id varchar(64) REFERENCES experiment_runs(id) ON DELETE SET NULL,
            producer_id varchar(64) NOT NULL,
            sequence bigint NOT NULL CHECK (sequence >= 0),
            measurement_type varchar(32) NOT NULL,
            value double precision NOT NULL,
            schema_version varchar(16) NOT NULL,
            CONSTRAINT fk_measurements_processed_event
                FOREIGN KEY (event_id) REFERENCES processed_event_ids(event_id) ON DELETE RESTRICT,
            CONSTRAINT pk_measurements PRIMARY KEY (event_id, generated_at),
            CONSTRAINT ck_measurement_type CHECK (measurement_type IN ('od', 'ph', 'temperature'))
        );
        SELECT create_hypertable('measurements', 'generated_at', if_not_exists => TRUE);
        CREATE INDEX ix_measurements_equipment_time
            ON measurements (equipment_id, generated_at DESC);
        CREATE INDEX ix_measurements_position_time
            ON measurements (position_id, generated_at DESC);
        CREATE INDEX ix_measurements_type_time
            ON measurements (measurement_type, generated_at DESC);
        CREATE INDEX ix_measurements_equipment_position_type_time
            ON measurements (equipment_id, position_id, measurement_type, generated_at DESC);
        CREATE INDEX ix_measurements_received_at ON measurements (received_at DESC);

        CREATE TABLE commands (
            command_id uuid PRIMARY KEY,
            equipment_id varchar(64) NOT NULL REFERENCES equipment(id) ON DELETE RESTRICT,
            experiment_run_id varchar(64) REFERENCES experiment_runs(id) ON DELETE SET NULL,
            author_id varchar(64) NOT NULL,
            target_type varchar(32) NOT NULL,
            target_id varchar(64) NOT NULL,
            action varchar(32) NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            status varchar(32) NOT NULL,
            result jsonb,
            created_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT ck_command_expiry CHECK (expires_at > created_at),
            CONSTRAINT ck_command_status CHECK (
                status IN ('requested', 'accepted', 'rejected', 'sent', 'received',
                           'executed', 'failed', 'unknown', 'expired')
            )
        );
        CREATE INDEX ix_commands_equipment_created ON commands (equipment_id, created_at DESC);
        CREATE INDEX ix_commands_status_expiry ON commands (status, expires_at);

        CREATE TABLE audit_events (
            id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            occurred_at timestamptz NOT NULL,
            actor_id varchar(64),
            action varchar(64) NOT NULL,
            entity_type varchar(64) NOT NULL,
            entity_id varchar(64) NOT NULL,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            correlation_id uuid
        );
        CREATE INDEX ix_audit_entity_time
            ON audit_events (entity_type, entity_id, occurred_at DESC);
        CREATE INDEX ix_audit_actor_time ON audit_events (actor_id, occurred_at DESC);

        CREATE VIEW latest_measurements AS
        SELECT DISTINCT ON (equipment_id, position_id, measurement_type)
            event_id, generated_at, received_at, equipment_id, position_id,
            experiment_run_id, producer_id, sequence, measurement_type, value, schema_version
        FROM measurements
        ORDER BY equipment_id, position_id, measurement_type,
                 generated_at DESC, sequence DESC, received_at DESC, event_id DESC;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS latest_measurements;
        DROP TABLE IF EXISTS audit_events;
        DROP TABLE IF EXISTS commands;
        DROP TABLE IF EXISTS measurements;
        DROP TABLE IF EXISTS processed_event_ids;
        DROP TABLE IF EXISTS experiment_runs;
        DROP TABLE IF EXISTS cultures;
        DROP TABLE IF EXISTS positions;
        DROP TABLE IF EXISTS equipment;
        """
    )
