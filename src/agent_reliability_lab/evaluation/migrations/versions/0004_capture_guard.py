"""Keep frozen scenario/oracle/evidence fields write-once at the database boundary."""

from alembic import op

revision = "0004_capture_guard"
down_revision = "0003_research"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION opsdesk_evaluation.guard_trial_capture() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'frozen trial deletion' USING ERRCODE='55000';
      END IF;
      IF NEW.scenario IS DISTINCT FROM OLD.scenario OR NEW.oracle IS DISTINCT FROM OLD.oracle
         OR NEW.scenario_hash IS DISTINCT FROM OLD.scenario_hash
         OR NEW.metadata IS DISTINCT FROM OLD.metadata
         OR NEW.experiment_id IS DISTINCT FROM OLD.experiment_id
         OR NEW.scenario_id IS DISTINCT FROM OLD.scenario_id
         OR NEW.scenario_version IS DISTINCT FROM OLD.scenario_version
         OR NEW.trial_index IS DISTINCT FROM OLD.trial_index
         OR (OLD.evidence IS NOT NULL AND (
             NEW.evidence IS DISTINCT FROM OLD.evidence
             OR NEW.evidence_hash IS DISTINCT FROM OLD.evidence_hash
             OR NEW.execution_id IS DISTINCT FROM OLD.execution_id
             OR NEW.ownership_marker IS DISTINCT FROM OLD.ownership_marker
             OR NEW.sandbox_run_id IS DISTINCT FROM OLD.sandbox_run_id)) THEN
        RAISE EXCEPTION 'frozen trial capture' USING ERRCODE='55000';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER immutable_capture BEFORE UPDATE OR DELETE ON
      opsdesk_evaluation.trials FOR EACH ROW
      EXECUTE FUNCTION opsdesk_evaluation.guard_trial_capture()""")


def downgrade():
    raise RuntimeError("removing a frozen-capture guard requires explicit preservation review")
