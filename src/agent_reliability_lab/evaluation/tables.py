"""Evaluation records never live in or depend on disposable business schemas."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData(schema="opsdesk_evaluation")
experiments = sa.Table(
    "experiments",
    metadata,
    sa.Column("experiment_id", sa.String(32), primary_key=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("manifest", JSONB, nullable=False),
    sa.Column("manifest_hash", sa.String(64), nullable=False),
)
trials = sa.Table(
    "trials",
    metadata,
    sa.Column("trial_id", sa.String(32), primary_key=True),
    sa.Column(
        "experiment_id",
        sa.String(32),
        sa.ForeignKey("opsdesk_evaluation.experiments.experiment_id"),
        nullable=False,
    ),
    sa.Column("scenario_id", sa.String(64), nullable=False),
    sa.Column("scenario_version", sa.Integer, nullable=False),
    sa.Column("scenario_hash", sa.String(64), nullable=False),
    sa.Column("trial_index", sa.Integer, nullable=False),
    sa.Column("metadata", JSONB, nullable=False),
    sa.Column("scenario", JSONB),
    sa.Column("oracle", JSONB, nullable=False),
    sa.Column("state", sa.String(32), nullable=False),
    sa.Column("execution_id", sa.String(32), unique=True),
    sa.Column("sandbox_run_id", sa.String(32), unique=True),
    sa.Column("ownership_marker", sa.String(36)),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("evidence", JSONB),
    sa.Column("evidence_hash", sa.String(64)),
    sa.Column("cleanup", JSONB, nullable=False),
    sa.UniqueConstraint("experiment_id", "scenario_id", "trial_index"),
    sa.CheckConstraint("trial_index >= 1"),
)
scores = sa.Table(
    "scores",
    metadata,
    sa.Column("scoring_id", sa.String(32), primary_key=True),
    sa.Column(
        "trial_id",
        sa.String(32),
        sa.ForeignKey("opsdesk_evaluation.trials.trial_id"),
        nullable=False,
    ),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("evaluator_version", sa.String(32), nullable=False),
    sa.Column("rules_hash", sa.String(64), nullable=False),
    sa.Column("result", JSONB, nullable=False),
    sa.Column("result_hash", sa.String(64), nullable=False),
    sa.UniqueConstraint("trial_id", "revision"),
)
reports = sa.Table(
    "reports",
    metadata,
    sa.Column("report_id", sa.String(32), primary_key=True),
    sa.Column(
        "experiment_id",
        sa.String(32),
        sa.ForeignKey("opsdesk_evaluation.experiments.experiment_id"),
        nullable=False,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("score_ids", JSONB, nullable=False),
    sa.Column("summary", JSONB, nullable=False),
    sa.Column("summary_hash", sa.String(64), nullable=False),
)
sa.Index("ix_eval_trial_scenario", trials.c.scenario_id, trials.c.scenario_version)
