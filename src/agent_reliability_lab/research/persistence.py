"""Append-only, hash-pinned research records. Human identity remains declared."""

import re

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from agent_reliability_lab.evaluation.persistence import EvaluationStore
from agent_reliability_lab.opsdesk.database import lock
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.contracts import Reference, parse_artifact

artifacts = sa.Table(
    "research_artifacts",
    sa.MetaData(schema="opsdesk_evaluation"),
    sa.Column("scope", sa.String(128), primary_key=True),
    sa.Column("kind", sa.String(32), primary_key=True),
    sa.Column("identity", sa.String(128), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("body", JSONB, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
)


class ResearchStore:
    def __init__(self, engine, scope="research"):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", scope):
            raise ValueError("invalid research scope")
        self.engine, self.scope = engine, scope
        self.evaluations = EvaluationStore(engine)

    async def initialize(self):
        await self.evaluations.initialize()

    def list(self, kind=None, identity=None):
        query = sa.select(artifacts).where(artifacts.c.scope == self.scope)
        if kind is not None:
            query = query.where(artifacts.c.kind == kind)
        if identity is not None:
            query = query.where(artifacts.c.identity == identity)
        with self.engine.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    query.order_by(artifacts.c.kind, artifacts.c.identity, artifacts.c.version)
                ).mappings()
            ]
        for row in rows:
            if digest(row["body"]) != row["content_hash"]:
                raise ValueError("research artifact integrity mismatch")
        return rows

    def get(self, reference):
        reference = (
            Reference.model_validate(reference) if isinstance(reference, dict) else reference
        )
        rows = self.list(reference.kind, reference.identity)
        row = next((r for r in rows if r["version"] == reference.version), None)
        if row is None or row["content_hash"] != reference.content_hash:
            raise ValueError("missing or conflicting frozen research reference")
        return parse_artifact(row["body"])

    def reference(self, artifact):
        return Reference(
            kind=artifact.kind,
            identity=artifact.identity,
            version=artifact.version,
            content_hash=digest(artifact.model_dump(mode="json")),
        )

    def append(self, artifact, *, human_attestation=False):
        value = artifact.model_dump(mode="json")
        artifact = parse_artifact(value)
        if self.evaluations.contains_sensitive(value):
            raise ValueError("sensitive research artifact rejected")
        if value.get("origin") == "human_declared" and not human_attestation:
            raise ValueError("a real human must explicitly attest; no automatic human review")
        if value.get("origin") == "synthetic_test" and not self.scope.startswith(
            ("test_", "demo_")
        ):
            raise ValueError("synthetic attestations require an isolated test/demo scope")
        with self.engine.begin() as connection:
            lock(connection, "research:" + self.scope)
            self._validate_references(artifact)
            last = connection.execute(
                sa.select(sa.func.max(artifacts.c.version)).where(
                    artifacts.c.scope == self.scope,
                    artifacts.c.kind == artifact.kind,
                    artifacts.c.identity == artifact.identity,
                )
            ).scalar_one()
            if artifact.version != (last or 0) + 1:
                raise ValueError("artifact versions must append consecutively")
            connection.execute(
                artifacts.insert().values(
                    scope=self.scope,
                    kind=artifact.kind,
                    identity=artifact.identity,
                    version=artifact.version,
                    body=value,
                    content_hash=digest(value),
                )
            )
        return self.reference(artifact)

    def _validate_references(self, item):
        if item.kind.startswith("benchmark_"):
            from agent_reliability_lab.research.benchmark import validate_references

            validate_references(self, item)
        elif item.kind in {"attestation", "adjudication"}:
            oracle = self.get(item.oracle)
            reviewer = self.get(item.reviewer if item.kind == "attestation" else item.adjudicator)
            if oracle.kind != "oracle" or reviewer.kind != "reviewer":
                raise ValueError("oracle and reviewer references must have the correct kind")
            current = self.list("reviewer", reviewer.identity)[-1]["body"]
            if (
                oracle.kind != "oracle"
                or reviewer.kind != "reviewer"
                or not reviewer.active
                or not current["active"]
            ):
                raise ValueError("invalid oracle or inactive reviewer")
            if item.author != reviewer.identity or reviewer.identity == oracle.author:
                raise ValueError(
                    "reviewer must attest personally and be distinct from oracle author"
                )
            if item.kind == "adjudication":
                existing = [
                    r
                    for r in self.list("adjudication")
                    if r["body"]["oracle"] == item.oracle.model_dump(mode="json")
                ]
                if existing and any(r["identity"] != item.identity for r in existing):
                    raise ValueError("one adjudication stream per oracle is required")
                if reviewer.role not in {"adjudicator", "both"} or current["role"] not in {
                    "adjudicator",
                    "both",
                }:
                    raise ValueError("adjudicator role required")
                reviews = [self.get(ref) for ref in item.attestations]
                if any(r.kind != "attestation" or r.oracle != item.oracle for r in reviews):
                    raise ValueError("adjudication must pin reviews of the same oracle")
                reviewers = {r.reviewer.identity for r in reviews}
                if len(reviewers) < 2 or reviewer.identity in reviewers:
                    raise ValueError("independent adjudicator and distinct reviewers required")
            else:
                if reviewer.role not in {"reviewer", "both"} or current["role"] not in {
                    "reviewer",
                    "both",
                }:
                    raise ValueError("reviewer role required")
                existing = [
                    r
                    for r in self.list("attestation")
                    if r["body"]["oracle"] == item.oracle.model_dump(mode="json")
                    and r["body"]["reviewer"]["identity"] == reviewer.identity
                ]
                if existing and any(r["identity"] != item.identity for r in existing):
                    raise ValueError("one attestation stream per oracle/reviewer is required")
        elif item.kind == "dataset_release":
            from agent_reliability_lab.research.partitions import validate_release

            validate_release(self, item)
        elif item.kind == "preregistration":
            split = self.get(item.split)
            if split.kind not in {"split", "dataset_release"} or not set(
                item.scenario_population
            ) <= {t.scenario_id for t in split.templates}:
                raise ValueError("preregistered population must belong to the frozen split")
            oracles = [self.get(ref) for ref in item.oracles]
            if any(o.kind != "oracle" for o in oracles) or not set(item.scenario_population) <= {
                o.scenario_id for o in oracles
            }:
                raise ValueError("a pinned oracle is required for every scenario")
        elif item.kind == "amendment":
            if self.get(item.preregistration).kind != "preregistration":
                raise ValueError("amendment requires a preregistration")
            if item.previous_amendment:
                previous = self.get(item.previous_amendment)
                if previous.kind != "amendment" or previous.preregistration != item.preregistration:
                    raise ValueError("amendment lineage conflict")
        elif item.kind == "pair":
            from agent_reliability_lab.research.pairing import verify_pair

            oracle = self.get(item.oracle)
            if oracle.kind != "oracle":
                raise ValueError("pair requires a versioned oracle")
            if item.dataset_release:
                release = self.get(item.dataset_release)
                if release.kind != "dataset_release" or not any(
                    t.scenario_id == oracle.scenario_id and t.content_hash == oracle.scenario_hash
                    for t in release.assignments
                ):
                    raise ValueError("pair dataset/scenario mismatch")
            for trial_id in (item.baseline_trial_id, item.guarded_trial_id):
                if trial_id is not None:
                    trial = self.evaluations.trial(trial_id)
                    if trial["scenario_hash"] != oracle.scenario_hash or trial[
                        "oracle"
                    ] != oracle.scoring_rules.model_dump(mode="json"):
                        raise ValueError("pair oracle does not match frozen trial rules")
            verified, criteria, reason = verify_pair(
                self.evaluations, item.baseline_trial_id, item.guarded_trial_id, item.oracle
            )
            if (item.verification, item.criteria, item.exclusion_reason) != (
                verified,
                criteria,
                reason,
            ):
                raise ValueError("pair verification does not match frozen trial evidence")
        elif item.kind == "analysis":
            from agent_reliability_lab.research.analysis import analyze
            from agent_reliability_lab.research.measurements import summarize_outcomes

            computed = analyze(
                self,
                item.pairs,
                item.dataset_release,
                item.evaluator_version,
                seed=item.seed,
                score_selections=item.score_selections,
            )
            computed["outcomes"] = summarize_outcomes(self, computed, seed=item.seed)
            if computed != item.result or digest(computed) != item.result_hash:
                raise ValueError("analysis must reproduce from exact frozen references")

    def review_status(self, oracle_ref):
        oracle = self.get(oracle_ref)
        latest = {}
        for row in self.list("attestation"):
            item = parse_artifact(row["body"])
            if item.oracle == oracle_ref:
                latest[item.reviewer.identity] = item
        reviews = list(latest.values())
        humans = [
            r
            for r in reviews
            if r.origin == "human_declared"
            and r.no_conflict_declared
            and self.get(r.reviewer).active
            and self.list("reviewer", r.reviewer.identity)[-1]["body"]["active"]
        ]
        material = [
            r for r in reviews if r.decision != "approve" or r.disagreement_class == "material"
        ]
        status = "pending_independent_human_review"
        adjudication = None
        if material:
            status = "unresolved_disagreement"
            hashes = {self.reference(r).content_hash for r in reviews}
            for row in self.list("adjudication"):
                a = parse_artifact(row["body"])
                if (
                    a.oracle == oracle_ref
                    and a.origin == "human_declared"
                    and a.no_conflict_declared
                    and self.list("reviewer", a.adjudicator.identity)[-1]["body"]["active"]
                    and self.list("reviewer", a.adjudicator.identity)[-1]["body"]["role"]
                    in {"adjudicator", "both"}
                    and {r.content_hash for r in a.attestations} == hashes
                ):
                    adjudication = self.reference(a).model_dump(mode="json")
                    status = (
                        "approved_declared_human_review"
                        if a.decision == "approve" and len(humans) >= 2
                        else "changes_required"
                    )
        elif len(humans) >= 2 and all(r.decision == "approve" for r in humans):
            status = "approved_declared_human_review"
        return dict(
            status=status,
            oracle_hash=self.reference(oracle).content_hash,
            review_count=len(reviews),
            review_references=[self.reference(r).model_dump(mode="json") for r in reviews],
            human_review_count=len(humans),
            identity_assurance="declared_unverified",
            adjudication=adjudication,
            independent_identity_verification=False,
        )

    def validate_study(self, reference, scenario_ids, *, accept_declared_reviewers=False):
        study = self.get(reference)
        if study.kind != "preregistration" or set(scenario_ids) != set(study.scenario_population):
            raise ValueError("study population mismatch")
        if study.mode == "confirmatory":
            if not accept_declared_reviewers or not study.evaluator_audit_reference:
                raise ValueError(
                    "confirmatory execution requires explicit human/evaluator audit acceptance"
                )
            if self.get(study.split).kind != "dataset_release":
                raise ValueError("confirmatory execution requires pinned composite partitions")
            for ref in study.oracles:
                if self.review_status(ref)["status"] != "approved_declared_human_review":
                    raise ValueError("confirmatory oracle review is pending or disputed")
            if self.list("amendment"):
                if any(
                    row["body"]["preregistration"] == reference.model_dump(mode="json")
                    for row in self.list("amendment")
                ):
                    raise ValueError(
                        "amended studies require a new preregistration before execution"
                    )
        return study
