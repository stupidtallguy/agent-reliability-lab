"""Add immutable report manifests; never rewrite historical reports or scores."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_reports"
down_revision = "0001_evaluation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "report_manifests",
        sa.Column(
            "report_id",
            sa.String(32),
            sa.ForeignKey("opsdesk_evaluation.reports.report_id"),
            primary_key=True,
        ),
        sa.Column("manifest", JSONB, nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        schema="opsdesk_evaluation",
    )
    op.execute("""CREATE FUNCTION opsdesk_evaluation.reject_frozen_mutation() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'frozen evaluation record' USING ERRCODE='55000'; END $$""")
    for table in ("experiments", "scores", "reports", "report_manifests"):
        op.execute(
            "CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE ON "
            f"opsdesk_evaluation.{table} "
            "FOR EACH ROW EXECUTE FUNCTION opsdesk_evaluation.reject_frozen_mutation()"
        )


def downgrade():
    raise RuntimeError("Destructive downgrade is disabled for preserved research evidence.")
