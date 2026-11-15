"""Bounded read-only data boundary for future presentation clients; no UI or scoring."""

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from agent_reliability_lab.agent import tables as a
from agent_reliability_lab.evaluation import tables as e
from agent_reliability_lab.research.persistence import artifacts


def readonly_engine(url):
    """Host-supplied URL only. Every transaction defaults to PostgreSQL read-only."""
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg":
        raise ValueError("dashboard requires PostgreSQL with Psycopg")
    return sa.create_engine(
        parsed,
        hide_parameters=True,
        pool_pre_ping=True,
        execution_options={"postgresql_readonly": True},
        connect_args={"options": "-c default_transaction_read_only=on -c statement_timeout=15000"},
    )


class ResearchView:
    def __init__(self, engine):
        self.engine = engine.execution_options(postgresql_readonly=True)

    def reliability_reports(self, execution_id, *, limit=50, on_invalid=None):
        from agent_reliability_lab.reliability.revisions import (
            current_state,
            report_rows,
            validated_reports,
        )

        if not 1 <= limit <= 100 or not isinstance(execution_id, str) or len(execution_id) != 32:
            raise ValueError("invalid reliability report selection")
        with self.engine.connect() as connection, connection.begin():
            connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            if not connection.scalar(sa.select(sa.func.to_regclass("opsdesk_reliability.reports"))):
                return []
            documents = []
            try:
                for document in validated_reports(
                    report_rows(connection, execution_id), execution_id, connection
                ):
                    if len(documents) < limit:
                        if document.verification == "verified":
                            document.current_state = current_state(connection, document)
                        documents.append(document)
            except (KeyError, TypeError, ValueError):
                if on_invalid is None:
                    raise
                on_invalid()
        return documents

    def rows(self, resource, *, identifier=None, kind=None, limit=50, offset=0):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid read-only pagination bounds")
        registry = dict(
            experiments=(e.experiments, "experiment_id"),
            trials=(e.trials, "experiment_id"),
            scores=(e.scores, "trial_id"),
            reports=(e.reports, "experiment_id"),
            report_manifests=(e.report_manifests, "report_id"),
            artifacts=(artifacts, "scope"),
            traces=(a.events, "execution_id"),
            provenance=(a.provenance, "execution_id"),
            executions=(a.executions, "execution_id"),
            decisions=(a.requests, "execution_id"),
            operations=(a.operations, "execution_id"),
            attempts=(a.attempts, "proposal_id"),
        )
        if resource not in registry:
            raise ValueError("unknown read-only research resource")
        table, key = registry[resource]
        query = sa.select(table)
        if identifier is not None:
            query = query.where(table.c[key] == identifier)
        if kind is not None:
            if resource != "artifacts":
                raise ValueError("kind applies only to research artifacts")
            query = query.where(table.c.kind == kind)
        with self.engine.connect() as connection, connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            return [
                dict(row)
                for row in connection.execute(
                    query.order_by(*table.primary_key.columns).limit(limit).offset(offset)
                ).mappings()
            ]

    def counts(self):
        with self.engine.connect() as connection, connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            return {
                name: connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
                for name, table in dict(
                    experiments=e.experiments, trials=e.trials, scores=e.scores, reports=e.reports
                ).items()
            }

    def experiment_inventory(self, *, limit=100, offset=0):
        """Bounded experiment summaries with materialized counts and stored context."""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid read-only pagination bounds")
        table = e.experiments
        counts = (
            sa.select(sa.func.count())
            .select_from(e.trials)
            .where(e.trials.c.experiment_id == table.c.experiment_id)
            .scalar_subquery()
        )
        ready = sa.exists().where(e.reports.c.experiment_id == table.c.experiment_id)
        manifest = table.c.manifest
        query = (
            sa.select(
                table.c.experiment_id,
                table.c.created_at,
                table.c.manifest_hash,
                manifest["purpose"].as_string().label("purpose"),
                manifest["demonstration"].label("demonstration"),
                manifest["config"]["defense"].as_string().label("configuration"),
                manifest["provenance"]["evaluator_version"].as_string().label("evaluator"),
                manifest["cases"].label("cases"),
                counts.label("trial_count"),
                ready.label("has_report"),
            )
            .order_by(table.c.created_at.desc(), table.c.experiment_id)
            .limit(limit)
            .offset(offset)
        )
        with self.engine.connect() as connection, connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            return [dict(row) for row in connection.execute(query).mappings()]

    def report_index(self, experiment_id, *, limit=100):
        """List pinned reports without loading summaries or selecting score cohorts."""
        if not 1 <= limit <= 100:
            raise ValueError("invalid read-only pagination bounds")
        reports, manifests = e.reports, e.report_manifests
        query = (
            sa.select(
                reports.c.report_id,
                reports.c.created_at,
                reports.c.score_ids,
                manifests.c.manifest["metric_definition_version"].as_string().label("evaluator"),
                manifests.c.manifest["renderer_version"].as_string().label("renderer"),
            )
            .select_from(reports.outerjoin(manifests, reports.c.report_id == manifests.c.report_id))
            .where(reports.c.experiment_id == experiment_id)
            .order_by(reports.c.created_at.desc(), reports.c.report_id)
            .limit(limit)
        )
        with self.engine.connect() as connection, connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            return [dict(row) for row in connection.execute(query).mappings()]

    def report(self, report_id):
        from agent_reliability_lab.evaluation.persistence import EvaluationStore
        from agent_reliability_lab.evaluation.reporting import reproduce

        return reproduce(EvaluationStore(self.engine), report_id)

    def experiment(self, experiment_id):
        from agent_reliability_lab.evaluation.persistence import EvaluationStore

        return EvaluationStore(self.engine).experiment(experiment_id)

    def trial(self, trial_id):
        from agent_reliability_lab.evaluation.persistence import EvaluationStore

        return EvaluationStore(self.engine).trial(trial_id)

    def readiness(self, scope):
        from agent_reliability_lab.research.contracts import parse_artifact
        from agent_reliability_lab.research.persistence import ResearchStore

        store = ResearchStore(self.engine, scope)
        records = store.list()
        oracles = [parse_artifact(r["body"]) for r in records if r["kind"] == "oracle"]
        reviews = [store.review_status(store.reference(o)) for o in oracles]
        releases = [parse_artifact(r["body"]) for r in records if r["kind"] == "dataset_release"]
        return dict(
            scope=scope,
            oracle_count=len(oracles),
            reviews=reviews,
            human_declared_attestations=sum(
                r["kind"] == "attestation" and r["body"].get("origin") == "human_declared"
                for r in records
            ),
            externally_verified_humans=None,
            held_out_count=max(
                (sum(t.split == "held_out" for t in release.assignments) for release in releases),
                default=0,
            ),
            preregistrations=[r for r in records if r["kind"] == "preregistration"],
            independent_audit_approval="not_recorded_by_this_interface",
            warning="Declared identities are not independent authentication or human approval.",
        )
