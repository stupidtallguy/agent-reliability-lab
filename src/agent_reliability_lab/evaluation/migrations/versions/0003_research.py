"""Append-only research artifacts, with no changes to historical scoring records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_research"
down_revision = "0002_reports"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "research_artifacts",
        sa.Column("scope", sa.String(128), primary_key=True),
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("identity", sa.String(128), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("body", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("version > 0"),
        schema="opsdesk_evaluation",
    )
    op.execute("""CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON
        opsdesk_evaluation.research_artifacts FOR EACH ROW
        EXECUTE FUNCTION opsdesk_evaluation.reject_frozen_mutation()""")


def downgrade():
    raise RuntimeError("research artifact deletion is not a safe downgrade")
