"""Seal new executions; prevent replacement of completed requests and journal rows."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_provenance"
down_revision = "0001_agent"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "provenance",
        sa.Column(
            "execution_id",
            sa.String(32),
            sa.ForeignKey("opsdesk_agent.executions.execution_id"),
            primary_key=True,
        ),
        sa.Column("sequence", sa.Integer, primary_key=True),
        sa.Column("record", JSONB, nullable=False),
        schema="opsdesk_agent",
    )
    op.execute("""CREATE FUNCTION opsdesk_agent.reject_history_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'immutable execution history' USING ERRCODE = '55000'; END $$""")
    for table in ("events", "provenance"):
        op.execute(
            f"CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON "
            f"opsdesk_agent.{table} FOR EACH ROW "
            "EXECUTE FUNCTION opsdesk_agent.reject_history_mutation()"
        )
    op.execute("""CREATE FUNCTION opsdesk_agent.complete_request_once() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'UPDATE' THEN
          IF OLD.status = 'started' AND OLD.reply IS NULL AND NEW.status = 'completed'
             AND NEW.reply IS NOT NULL AND OLD.request_id = NEW.request_id
             AND OLD.execution_id = NEW.execution_id AND OLD.turn = NEW.turn THEN
            RETURN NEW;
          END IF;
        END IF;
        RAISE EXCEPTION 'immutable model decision' USING ERRCODE = '55000'; END $$""")
    op.execute("""CREATE TRIGGER immutable_request BEFORE UPDATE OR DELETE ON
        opsdesk_agent.model_requests FOR EACH ROW
        EXECUTE FUNCTION opsdesk_agent.complete_request_once()""")


def downgrade():
    raise RuntimeError("provenance downgrade requires an explicit preservation plan")
