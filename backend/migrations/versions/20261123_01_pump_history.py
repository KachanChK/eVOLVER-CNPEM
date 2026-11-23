"""Record changes to observable pump state independently of command intent."""

from alembic import op

revision = "20261123_01"
down_revision = "20261122_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pump_transitions (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            experiment_id bigint NOT NULL REFERENCES experiments (id),
            observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            paused boolean NOT NULL,
            confirmed_state varchar(16) NOT NULL,
            reason varchar(32) NOT NULL,
            command_id uuid REFERENCES pump_commands (command_id)
        )
    """)
    op.execute("""
        CREATE INDEX ix_pump_transitions_experiment ON pump_transitions (experiment_id, id)
    """)
    op.execute("""
        INSERT INTO pump_transitions (experiment_id, paused, confirmed_state, reason)
        SELECT c.experiment_id, c.paused OR c.resume_pending OR c.ending,
               c.confirmed_state, 'history_started'
        FROM pump_control c JOIN experiments e ON e.id = c.experiment_id
        WHERE e.ended_at IS NULL
    """)
    op.execute("""
        CREATE FUNCTION record_pump_transition() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            mode_paused boolean := NEW.paused OR NEW.resume_pending OR NEW.ending;
            change_reason text;
            completed_command uuid;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                change_reason := 'initial';
            ELSIF NEW.ending AND NOT OLD.ending THEN
                change_reason := 'ending';
            ELSIF mode_paused AND NOT (OLD.paused OR OLD.resume_pending OR OLD.ending) THEN
                change_reason := 'pause';
            ELSIF NOT mode_paused AND (OLD.paused OR OLD.resume_pending OR OLD.ending) THEN
                change_reason := 'resume';
            ELSIF NEW.confirmed_state IS DISTINCT FROM OLD.confirmed_state THEN
                IF NEW.pending_command_id IS NULL AND OLD.pending_command_id IS NOT NULL THEN
                    SELECT reason INTO change_reason FROM pump_commands
                    WHERE command_id = OLD.pending_command_id AND result_status = 'executed';
                    IF FOUND THEN
                        completed_command := OLD.pending_command_id;
                    END IF;
                END IF;
                change_reason := coalesce(change_reason, 'confirmation_lost');
            ELSE
                RETURN NEW;
            END IF;
            INSERT INTO pump_transitions
                (experiment_id, paused, confirmed_state, reason, command_id)
            VALUES (NEW.experiment_id, mode_paused, NEW.confirmed_state,
                    change_reason, completed_command);
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER pump_control_history
        AFTER INSERT OR UPDATE OF paused, resume_pending, ending, confirmed_state ON pump_control
        FOR EACH ROW EXECUTE FUNCTION record_pump_transition()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER pump_control_history ON pump_control")
    op.execute("DROP FUNCTION record_pump_transition()")
    op.drop_table("pump_transitions")
