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
            vial_id varchar(64) NOT NULL,
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL,
            CONSTRAINT uq_positions_equipment_code UNIQUE (equipment_id, position_code),
            CONSTRAINT uq_positions_equipment_id_id UNIQUE (equipment_id, id)
        );
        CREATE UNIQUE INDEX uq_positions_enabled_vial
            ON positions (vial_id) WHERE enabled;

        CREATE TABLE cultures (
            id uuid PRIMARY KEY,
            vial_id varchar(64) NOT NULL,
            organism varchar(120),
            label varchar(120),
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL
        );

        CREATE TABLE experiment_runs (
            id varchar(64) PRIMARY KEY,
            equipment_id varchar(64) NOT NULL,
            position_id uuid NOT NULL,
            culture_id uuid REFERENCES cultures(id) ON DELETE SET NULL,
            started_at timestamptz NOT NULL,
            ended_at timestamptz,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_run_time_order CHECK (ended_at IS NULL OR ended_at >= started_at),
            CONSTRAINT fk_experiment_runs_equipment_position
                FOREIGN KEY (equipment_id, position_id)
                REFERENCES positions (equipment_id, id) ON DELETE RESTRICT
        );
        CREATE INDEX ix_experiment_runs_position_started
            ON experiment_runs (position_id, started_at DESC);

        CREATE TABLE processed_event_ids (
            event_id uuid PRIMARY KEY,
            equipment_id varchar(64),
            producer_id varchar(64),
            generated_at timestamptz,
            received_at timestamptz NOT NULL,
            outcome varchar(16) NOT NULL DEFAULT 'persisted',
            CONSTRAINT ck_processed_event_outcome CHECK (outcome IN ('persisted', 'quarantined')),
            CONSTRAINT ck_processed_event_persisted_fields CHECK (
                outcome = 'quarantined' OR
                (equipment_id IS NOT NULL AND producer_id IS NOT NULL AND generated_at IS NOT NULL)
            ),
            CONSTRAINT uq_processed_event_ids_event_generated UNIQUE (event_id, generated_at)
        );
        CREATE INDEX ix_processed_event_ids_received_at ON processed_event_ids (received_at DESC);

        CREATE TABLE measurements (
            event_id uuid NOT NULL,
            generated_at timestamptz NOT NULL,
            received_at timestamptz NOT NULL,
            equipment_id varchar(64) NOT NULL,
            position_id uuid NOT NULL,
            experiment_run_id varchar(64) REFERENCES experiment_runs(id) ON DELETE SET NULL,
            producer_id varchar(64) NOT NULL,
            sequence bigint NOT NULL,
            measurement_type varchar(32) NOT NULL,
            value double precision NOT NULL,
            schema_version varchar(16) NOT NULL,
            CONSTRAINT fk_measurements_processed_event
                FOREIGN KEY (event_id, generated_at)
                REFERENCES processed_event_ids(event_id, generated_at) ON DELETE RESTRICT,
            CONSTRAINT fk_measurements_equipment_position
                FOREIGN KEY (equipment_id, position_id)
                REFERENCES positions(equipment_id, id) ON DELETE RESTRICT,
            CONSTRAINT pk_measurements PRIMARY KEY (event_id, generated_at),
            CONSTRAINT ck_measurement_sequence CHECK (sequence >= 0),
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
        SELECT latest.event_id, latest.generated_at, latest.received_at,
               latest.equipment_id, latest.position_id, latest.experiment_run_id,
               latest.producer_id, latest.sequence, latest.measurement_type,
               latest.value, latest.schema_version
        FROM positions AS position
        CROSS JOIN (VALUES ('od'::varchar), ('ph'::varchar), ('temperature'::varchar))
            AS measurement_types(measurement_type)
        CROSS JOIN LATERAL (
            SELECT measurement.event_id, measurement.generated_at, measurement.received_at,
                   measurement.equipment_id, measurement.position_id,
                   measurement.experiment_run_id, measurement.producer_id,
                   measurement.sequence, measurement.measurement_type,
                   measurement.value, measurement.schema_version
            FROM measurements AS measurement
            WHERE measurement.equipment_id = position.equipment_id
              AND measurement.position_id = position.id
              AND measurement.measurement_type = measurement_types.measurement_type
            ORDER BY measurement.generated_at DESC, measurement.sequence DESC,
                     measurement.received_at DESC, measurement.event_id DESC
            LIMIT 1
        ) AS latest;
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
