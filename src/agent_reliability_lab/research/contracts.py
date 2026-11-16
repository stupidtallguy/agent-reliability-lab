"""Research artifacts are versioned separately from evaluator and application code."""

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from agent_reliability_lab.benchmarks.scenario import Contract, Identifier
from agent_reliability_lab.evaluation.contracts import OracleSpec


class Reference(Contract):
    kind: str
    identity: Identifier
    version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Artifact(Contract):
    schema_version: Literal["1.0"] = "1.0"
    identity: Identifier
    version: int = Field(default=1, ge=1)
    created_at: AwareDatetime
    author: Identifier


class Reviewer(Artifact):
    kind: Literal["reviewer"] = "reviewer"
    display_name: str = Field(min_length=1, max_length=200)
    affiliation: str | None = Field(default=None, max_length=200)
    role: Literal["reviewer", "adjudicator", "both"] = "reviewer"
    identity_verification: Literal["declared_unverified"] = "declared_unverified"
    conflict_of_interest: str = Field(min_length=1, max_length=2000)
    active: bool = True


class Oracle(Artifact):
    kind: Literal["oracle"] = "oracle"
    scenario_id: Identifier
    scenario_version: int = Field(ge=1)
    scenario_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    legitimate_behavior: str = Field(min_length=1, max_length=8000)
    prohibited_behavior: str = Field(min_length=1, max_length=8000)
    state_assertions: list[dict]
    response_assertions: list[dict]
    trace_assertions: list[dict]
    attack_objective: dict | None
    evidence_requirements: list[str] = Field(min_length=1)
    metric_eligibility: dict[str, bool]
    scoring_rules: OracleSpec
    review_status: Literal["pending"] = "pending"


class Attestation(Artifact):
    kind: Literal["attestation"] = "attestation"
    oracle: Reference
    reviewer: Reference
    decision: Literal["approve", "changes_required", "reject"]
    disagreement_class: Literal["none", "material", "clarification"]
    rationale: str = Field(min_length=1, max_length=8000)
    evidence_references: list[str] = Field(min_length=1)
    no_conflict_declared: bool
    origin: Literal["human_declared", "synthetic_test"]


class Adjudication(Artifact):
    no_conflict_declared: bool = False
    kind: Literal["adjudication"] = "adjudication"
    oracle: Reference
    adjudicator: Reference
    attestations: list[Reference] = Field(min_length=2)
    decision: Literal["approve", "changes_required", "reject"]
    rationale: str = Field(min_length=1, max_length=8000)
    evidence_references: list[str] = Field(min_length=1)
    origin: Literal["human_declared", "synthetic_test"]


class Template(Contract):
    scenario_id: Identifier
    scenario_version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    template_id: Identifier
    family_id: Identifier
    mechanism: str
    lineage: list[str]
    split: Literal["development", "held_out"]


class SplitManifest(Artifact):
    kind: Literal["split"] = "split"
    templates: list[Template]
    generalization_validated: Literal[False] = False

    @model_validator(mode="after")
    def disjoint(self) -> Self:
        families = {}
        ids = set()
        for item in self.templates:
            if item.scenario_id in ids:
                raise ValueError("duplicate scenario in split")
            ids.add(item.scenario_id)
            if families.setdefault(item.family_id, item.split) != item.split:
                raise ValueError("template family crosses development/held-out boundary")
        return self


class DatasetRelease(Artifact):
    """One immutable release binds all partitions; empty held-out stays explicit."""

    kind: Literal["dataset_release"] = "dataset_release"
    validation_version: Literal["partitions_v1"] = "partitions_v1"
    development: Reference
    held_out: Reference
    assignments: list[Template]

    @property
    def templates(self):
        return self.assignments


class Preregistration(Artifact):
    kind: Literal["preregistration"] = "preregistration"
    mode: Literal["exploratory", "pilot", "confirmatory"]
    research_question: str = Field(min_length=1)
    hypotheses: list[str] = Field(min_length=1)
    primary_outcome: str
    secondary_outcomes: list[str]
    configurations: dict
    model: dict
    scenario_population: list[Identifier] = Field(min_length=1)
    categories: list[str]
    sample_size: int = Field(ge=1)
    sample_size_rationale: str | None = Field(default=None, exclude_if=lambda v: v is None)
    trial_allocation: dict
    pairing_design: dict
    oracles: list[Reference] = Field(min_length=1)
    evaluator_version: str
    evaluator_audit_reference: str | None = None
    split: Reference
    exclusion_rules: list[str]
    missing_data_rules: list[str] = Field(min_length=1)
    statistical_plan: dict
    interval_method: str
    planned_comparisons: list[str]
    stopping_rules: list[str] = Field(min_length=1)
    budget_limits: dict
    approval_status: Literal["pending_human_review"] = "pending_human_review"


class Amendment(Artifact):
    kind: Literal["amendment"] = "amendment"
    preregistration: Reference
    previous_amendment: Reference | None = None
    reason: str = Field(min_length=1)
    changed_fields: dict = Field(min_length=1)
    confirmatory_impact: Literal["exploratory_only", "requires_new_preregistration"]


class Pair(Artifact):
    kind: Literal["pair"] = "pair"
    pair_group: Identifier
    baseline_trial_id: str
    guarded_trial_id: str | None
    intended_difference: Literal["defense_configuration"] = "defense_configuration"
    oracle: Reference
    dataset_release: Reference | None = Field(default=None, exclude_if=lambda v: v is None)
    criteria: dict
    verification: Literal["verified", "incomplete", "excluded"]
    exclusion_reason: str | None


class AnalysisRecord(Artifact):
    kind: Literal["analysis"] = "analysis"
    interpretation: Literal["exploratory_descriptive"] = "exploratory_descriptive"
    pairs: list[Reference]
    dataset_release: Reference
    evaluator_version: str
    score_selections: dict[str, dict]
    seed: int = 0
    result: dict
    result_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


ARTIFACTS = {
    m.model_fields["kind"].default: m
    for m in (
        Reviewer,
        Oracle,
        Attestation,
        Adjudication,
        SplitManifest,
        DatasetRelease,
        Preregistration,
        Amendment,
        Pair,
        AnalysisRecord,
    )
}


def parse_artifact(value):
    import json

    kind = value.get("kind") if isinstance(value, dict) else None
    if not isinstance(kind, str):
        raise ValueError("research artifact kind is required")
    model = ARTIFACTS.get(kind)
    if model is None and kind.startswith("benchmark_"):
        from agent_reliability_lab.research.benchmark_contracts import CONTRACTS

        model = CONTRACTS.get(kind)
        if model is None:
            from agent_reliability_lab.research.heldout_contracts import (
                CONTRACTS as DESIGN_CONTRACTS,
            )

            model = DESIGN_CONTRACTS.get(kind)
        if model is None:
            from agent_reliability_lab.research.confirmatory_contracts import (
                CONTRACTS as CP14_CONTRACTS,
            )

            model = CP14_CONTRACTS.get(kind)
        if model is None:
            from agent_reliability_lab.research.pilot_contracts import PilotPlan, PilotReport

            model = {"benchmark_pilot_plan": PilotPlan, "benchmark_pilot_report": PilotReport}.get(
                kind
            )
        if kind == "benchmark_live_authorization":
            from agent_reliability_lab.research.live_contracts import LiveAuthorization

            model = LiveAuthorization
    if model is None:
        raise ValueError("unsupported research artifact kind")
    return model.model_validate_json(json.dumps(value))
