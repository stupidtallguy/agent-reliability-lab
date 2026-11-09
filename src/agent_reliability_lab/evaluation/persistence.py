"""Guarded migrations, immutable evidence/scoring versions and scoped retrieval."""

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateSchema

from agent_reliability_lab.agent.journal import Redactor
from agent_reliability_lab.benchmarks.scenario import Scenario
from agent_reliability_lab.evaluation import tables as t
from agent_reliability_lab.evaluation.contracts import EvaluationResult, Evidence, OracleSpec
from agent_reliability_lab.opsdesk.database import _MIGRATION_LOCK, SandboxManager, lock
from agent_reliability_lab.opsdesk.fixtures import digest


def now() -> datetime:
    return datetime.now(UTC)


class EvaluationStore:
    def __init__(self, engine: Engine):
        SandboxManager(engine)
        self.engine = engine
        self.redactor = Redactor()

    def contains_sensitive(self, value) -> bool:
        """Reject credentials without treating scenario IDs as HTTP header names."""
        if isinstance(value, str):
            if self.redactor.text(value) != value:
                return True
            try:
                nested = json.loads(value)
            except ValueError:
                return False
            return self.contains_sensitive(nested) if isinstance(nested, (dict, list)) else False
        if isinstance(value, list):
            return any(self.contains_sensitive(item) for item in value)
        if isinstance(value, dict):
            names = {
                "password",
                "api_key",
                "signing_key",
                "authorization",
                "signature",
                "database_url",
                "access_token",
                "refresh_token",
            }
            return any(
                str(key).casefold() in names
                or self.contains_sensitive(str(key))
                or self.contains_sensitive(item)
                for key, item in value.items()
            )
        return False

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        with self.engine.begin() as connection:
            lock(connection, "evaluation_migrations")
            connection.execute(CreateSchema("opsdesk_evaluation", if_not_exists=True))
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
            config.attributes["connection"] = connection
            with _MIGRATION_LOCK:
                command.upgrade(config, "head")

    def create_experiment(self, manifest: dict) -> str:
        if self.contains_sensitive(manifest):
            raise ValueError("experiment contains sensitive data")
        identifier = uuid.uuid4().hex
        with self.engine.begin() as connection:
            connection.execute(
                t.experiments.insert().values(
                    experiment_id=identifier,
                    created_at=now(),
                    manifest=manifest,
                    manifest_hash=digest(manifest),
                )
            )
        return identifier

    def experiment(self, experiment_id: str) -> dict:
        with self.engine.connect() as connection:
            row = dict(
                connection.execute(
                    sa.select(t.experiments).where(t.experiments.c.experiment_id == experiment_id)
                )
                .mappings()
                .one()
            )
        if digest(row["manifest"]) != row["manifest_hash"]:
            raise ValueError("manifest integrity mismatch")
        return row

    def create_trial(
        self,
        experiment_id: str,
        scenario: Scenario | None,
        scenario_hash: str,
        oracle: OracleSpec,
        trial_index: int,
        mode: str,
    ) -> dict:
        if scenario and self.contains_sensitive(scenario.model_dump(mode="json")):
            raise ValueError("sensitive scenario cannot be persisted")
        trial_id = uuid.uuid4().hex
        meta = {
            "experiment_id": experiment_id,
            "trial_id": trial_id,
            "scenario_id": scenario.scenario_id if scenario else "invalid_" + scenario_hash[:16],
            "scenario_version": scenario.scenario_version if scenario else 0,
            "scenario_hash": scenario_hash,
            "trial_index": trial_index,
            "mode": mode,
            "category": scenario.category if scenario else "invalid",
            "split": scenario.metadata.split if scenario else "unknown",
            "execution_id": None,
            "oracle_hash": digest(oracle.model_dump(mode="json")),
        }
        with self.engine.begin() as connection:
            connection.execute(
                t.trials.insert().values(
                    trial_id=trial_id,
                    experiment_id=experiment_id,
                    scenario_id=meta["scenario_id"],
                    scenario_version=meta["scenario_version"],
                    scenario_hash=scenario_hash,
                    trial_index=trial_index,
                    metadata=meta,
                    scenario=scenario.model_dump(mode="json") if scenario else None,
                    oracle=oracle.model_dump(mode="json"),
                    state="planned",
                    cleanup={"status": "not_provisioned"},
                )
            )
        return meta

    def update_trial(self, trial_id: str, **values) -> None:
        allowed = {
            "state",
            "execution_id",
            "sandbox_run_id",
            "ownership_marker",
            "started_at",
            "completed_at",
            "cleanup",
        }
        if not values.keys() <= allowed:
            raise ValueError("immutable trial fields cannot be updated")
        with self.engine.begin() as connection:
            connection.execute(
                t.trials.update().where(t.trials.c.trial_id == trial_id).values(**values)
            )

    def save_evidence(self, trial_id: str, evidence: Evidence) -> None:
        payload = evidence.model_dump(mode="json")
        if self.contains_sensitive(payload):
            raise ValueError("sensitive evidence cannot be persisted")
        with self.engine.begin() as connection:
            changed = connection.execute(
                t.trials.update()
                .where(
                    t.trials.c.trial_id == trial_id,
                    t.trials.c.evidence.is_(None),
                    t.trials.c.execution_id == evidence.execution_id,
                    t.trials.c.ownership_marker == evidence.marker,
                )
                .values(
                    evidence=payload,
                    evidence_hash=digest(payload),
                    state="captured",
                    completed_at=now(),
                )
            )
            if changed.rowcount != 1:
                raise ValueError("evidence already frozen or trial association differs")

    def trial(self, trial_id: str) -> dict:
        with self.engine.connect() as connection:
            row = dict(
                connection.execute(sa.select(t.trials).where(t.trials.c.trial_id == trial_id))
                .mappings()
                .one()
            )
        if row["evidence"] is not None and digest(row["evidence"]) != row["evidence_hash"]:
            raise ValueError("frozen evidence integrity mismatch")
        if row["scenario"] is not None and digest(row["scenario"]) != row["scenario_hash"]:
            raise ValueError("scenario integrity mismatch")
        if (
            row["metadata"].get("oracle_hash")
            and digest(row["oracle"]) != row["metadata"]["oracle_hash"]
        ):
            raise ValueError("original oracle integrity mismatch")
        row["metadata"] = {**row["metadata"], "execution_id": row["execution_id"]}
        return row

    def list_trials(self, *, experiment_id=None, scenario_id=None, execution_id=None) -> list[dict]:
        query = sa.select(t.trials.c.trial_id)
        for name, value in {
            "experiment_id": experiment_id,
            "scenario_id": scenario_id,
            "execution_id": execution_id,
        }.items():
            if value is not None:
                query = query.where(t.trials.c[name] == value)
        with self.engine.connect() as connection:
            ids = list(
                connection.execute(
                    query.order_by(t.trials.c.scenario_id, t.trials.c.trial_index)
                ).scalars()
            )
        return [self.trial(identifier) for identifier in ids]

    def save_score(self, result: EvaluationResult) -> int:
        payload = result.model_dump(mode="json")
        if self.contains_sensitive(payload):
            raise ValueError("sensitive scoring result cannot be persisted")
        with self.engine.begin() as connection:
            trial = (
                connection.execute(
                    sa.select(t.trials)
                    .where(t.trials.c.trial_id == result.trial_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            for key in (
                "experiment_id",
                "scenario_id",
                "scenario_version",
                "scenario_hash",
                "trial_index",
                "execution_id",
            ):
                if getattr(result, key) != trial[key]:
                    raise ValueError("score trial/execution association mismatch")
            if result.eligible and result.evidence_hash != trial["evidence_hash"]:
                raise ValueError("score evidence hash mismatch")
            if digest(result.oracle_spec) != result.rules_hash:
                raise ValueError("score oracle hash mismatch")
            revision = (
                connection.execute(
                    sa.select(sa.func.coalesce(sa.func.max(t.scores.c.revision), 0)).where(
                        t.scores.c.trial_id == result.trial_id
                    )
                ).scalar_one()
                + 1
            )
            connection.execute(
                t.scores.insert().values(
                    scoring_id=result.scoring_id,
                    trial_id=result.trial_id,
                    revision=revision,
                    created_at=now(),
                    evaluator_version=result.evaluator_version,
                    rules_hash=result.rules_hash,
                    result=payload,
                    result_hash=digest(payload),
                )
            )
        return revision

    def scores(self, trial_id: str) -> list[EvaluationResult]:
        with self.engine.connect() as connection:
            rows = list(
                connection.execute(
                    sa.select(t.scores)
                    .where(t.scores.c.trial_id == trial_id)
                    .order_by(t.scores.c.revision)
                ).mappings()
            )
        for row in rows:
            if digest(row["result"]) != row["result_hash"]:
                raise ValueError("score integrity mismatch")
        return [EvaluationResult.model_validate_json(json.dumps(row["result"])) for row in rows]

    def save_report(self, experiment_id: str, scores: list[EvaluationResult], summary: dict) -> str:
        report_id = uuid.uuid4().hex
        with self.engine.begin() as connection:
            connection.execute(
                t.reports.insert().values(
                    report_id=report_id,
                    experiment_id=experiment_id,
                    created_at=now(),
                    score_ids=[score.scoring_id for score in scores],
                    summary=summary,
                    summary_hash=digest(summary),
                )
            )
        return report_id

    def save_report_bundle(self, experiment_id, scores, summary, envelope):
        report_id = uuid.uuid4().hex
        envelope = {**envelope, "report_id": report_id, "generated_at": now().isoformat()}

        # Schema-defined distributions have labels, not authentication headers.
        # Preserve every label/value for string/secret inspection, recursively.
        def inspection(value):
            if isinstance(value, list):
                return [inspection(item) for item in value]
            if isinstance(value, dict):
                return {
                    key: dict(labels=list(item), values=[inspection(v) for v in item.values()])
                    if key in {"per_category", "per_scenario", "scenario_distribution"}
                    and isinstance(item, dict)
                    else inspection(item)
                    for key, item in value.items()
                }
            return value

        if self.contains_sensitive([inspection(summary), envelope]):
            raise ValueError("sensitive report cannot be persisted")
        with self.engine.begin() as connection:
            rows = list(
                connection.execute(
                    sa.select(t.scores, t.trials.c.experiment_id)
                    .join(t.trials)
                    .where(t.scores.c.scoring_id.in_([s.scoring_id for s in scores]))
                ).mappings()
            )
            actual = {r["scoring_id"]: r for r in rows}
            if len(actual) != len(scores) or any(
                actual[s.scoring_id]["experiment_id"] != experiment_id
                or actual[s.scoring_id]["result_hash"] != digest(s.model_dump(mode="json"))
                for s in scores
            ):
                raise ValueError("report score association mismatch")
            for selected in envelope["selected_scores"]:
                if selected["revision"] != actual[selected["scoring_id"]]["revision"]:
                    raise ValueError("report revision mismatch")
            connection.execute(
                t.reports.insert().values(
                    report_id=report_id,
                    experiment_id=experiment_id,
                    created_at=now(),
                    score_ids=[s.scoring_id for s in scores],
                    summary=summary,
                    summary_hash=digest(summary),
                )
            )
            connection.execute(
                t.report_manifests.insert().values(
                    report_id=report_id,
                    manifest=envelope,
                    manifest_hash=digest(envelope),
                    content_hash=envelope["content_hash"],
                )
            )
        return report_id, envelope

    def saved_report(self, report_id):
        with self.engine.connect() as c:
            row = dict(
                c.execute(sa.select(t.reports).where(t.reports.c.report_id == report_id))
                .mappings()
                .one()
            )
            manifest = (
                c.execute(
                    sa.select(t.report_manifests).where(t.report_manifests.c.report_id == report_id)
                )
                .mappings()
                .one_or_none()
            )
            records = list(
                c.execute(
                    sa.select(t.scores).where(t.scores.c.scoring_id.in_(row["score_ids"]))
                ).mappings()
            )
        if digest(row["summary"]) != row["summary_hash"]:
            raise ValueError("report integrity mismatch")
        if manifest and digest(manifest["manifest"]) != manifest["manifest_hash"]:
            raise ValueError("report manifest integrity mismatch")
        if any(digest(r["result"]) != r["result_hash"] for r in records):
            raise ValueError("score integrity mismatch")
        by_id = {r["scoring_id"]: r for r in records}
        if set(by_id) != set(row["score_ids"]):
            raise ValueError("missing report score")
        return row, dict(manifest) if manifest else None, [by_id[i] for i in row["score_ids"]]
