"""Execution metadata is separate from synthetic business schemas."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData(schema="opsdesk_agent")
executions = sa.Table(
    "executions",
    metadata,
    sa.Column("execution_id", sa.String(32), primary_key=True),
    sa.Column("thread_id", sa.String(32), nullable=False, unique=True),
    sa.Column("config", JSONB, nullable=False),
    sa.Column("config_hash", sa.String(64), nullable=False),
    sa.Column("context", JSONB, nullable=False),
    sa.Column("task", sa.Text, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
    sa.Column("elapsed_ms", sa.Float, nullable=False),
    sa.Column("timing_complete", sa.Boolean, nullable=False),
    sa.Column("llm_calls", sa.Integer, nullable=False),
    sa.Column("tool_calls", sa.Integer, nullable=False),
    sa.Column("graph_steps", sa.Integer, nullable=False),
    sa.Column("journal_seq", sa.Integer, nullable=False),
    sa.Column("result", JSONB),
    sa.Column("checkpoint_id", sa.String(128)),
    sa.CheckConstraint(
        "llm_calls >= 0 AND tool_calls >= 0 AND graph_steps >= 0 AND elapsed_ms >= 0"
    ),
)
events = sa.Table(
    "events",
    metadata,
    sa.Column(
        "execution_id",
        sa.String(32),
        sa.ForeignKey("opsdesk_agent.executions.execution_id"),
        primary_key=True,
    ),
    sa.Column("sequence", sa.Integer, primary_key=True),
    sa.Column("event_type", sa.String(64), nullable=False),
    sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    sa.Column("elapsed_ms", sa.Float, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
)
requests = sa.Table(
    "model_requests",
    metadata,
    sa.Column("request_id", sa.String(32), primary_key=True),
    sa.Column(
        "execution_id",
        sa.String(32),
        sa.ForeignKey("opsdesk_agent.executions.execution_id"),
        nullable=False,
    ),
    sa.Column("turn", sa.Integer, nullable=False),
    sa.Column("reply", JSONB),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("duration_ms", sa.Float),
)
operations = sa.Table(
    "operations",
    metadata,
    sa.Column("proposal_id", sa.String(32), primary_key=True),
    sa.Column(
        "execution_id",
        sa.String(32),
        sa.ForeignKey("opsdesk_agent.executions.execution_id"),
        nullable=False,
    ),
    sa.Column("turn", sa.Integer, nullable=False),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("tool", sa.String(128), nullable=False),
    sa.Column("model_call_id", sa.String(128), nullable=False),
    sa.Column("operation_id", sa.String(32), unique=True),
    sa.Column("arguments", JSONB, nullable=False),
    sa.Column("arguments_hash", sa.String(64), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("response", JSONB),
    sa.UniqueConstraint("execution_id", "turn", "position"),
)
attempts = sa.Table(
    "tool_attempts",
    metadata,
    sa.Column("attempt_id", sa.String(32), primary_key=True),
    sa.Column(
        "proposal_id",
        sa.String(32),
        sa.ForeignKey("opsdesk_agent.operations.proposal_id"),
        nullable=False,
    ),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("duration_ms", sa.Float),
    sa.Column("error_code", sa.String(64)),
    sa.Column("effect", sa.String(32), nullable=False),
    sa.UniqueConstraint("proposal_id", "ordinal"),
)
sa.Index("ix_model_turn", requests.c.execution_id, requests.c.turn)
