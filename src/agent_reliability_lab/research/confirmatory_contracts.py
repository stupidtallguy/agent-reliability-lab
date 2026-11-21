"""Content-free allocation, future budget and confirmatory publication contracts."""

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from agent_reliability_lab.benchmarks.scenario import Contract, Identifier
from agent_reliability_lab.research.benchmark_contracts import UUID, Hash
from agent_reliability_lab.research.contracts import Artifact, Reference

Arm = Literal["baseline", "guarded"]
Positive = Annotated[int, Field(gt=0)]
Nonnegative = Annotated[int, Field(ge=0)]


class ModelIdentity(Contract):
    provider: Identifier
    model_id: Annotated[str, Field(min_length=1, max_length=128)]


class FutureBudget(Contract):
    version: Literal["reservation_limits_v1"] = "reservation_limits_v1"
    models: list[ModelIdentity] = Field(min_length=1, max_length=20)
    configuration_hash: Hash
    max_model_calls: Positive
    max_calls_per_scenario: Positive
    max_total_tokens: Positive
    max_cost_usd: Decimal = Field(gt=0, allow_inf_nan=False)
    max_duration_ms: Positive
    max_retries_per_scenario: Nonnegative

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len({(m.provider, m.model_id) for m in self.models}) != len(self.models):
            raise ValueError("model allowlist identities must be unique")
        if self.max_calls_per_scenario > self.max_model_calls:
            raise ValueError("scenario budget exceeds experiment-wide call budget")
        return self


class BudgetUsage(Contract):
    budget_hash: Hash
    allocation_hash: Hash
    duration_ms: Nonnegative = 0
    held_tokens: Nonnegative = 0
    held_usd: Decimal = Field(default=Decimal("0"), ge=0, allow_inf_nan=False)
    calls: dict[Hash, Positive] = Field(default_factory=dict)
    retries: dict[Hash, Positive] = Field(default_factory=dict)


class ReservationRequest(Contract):
    model: ModelIdentity
    configuration_hash: Hash
    scenario: Hash
    elapsed_ms: Nonnegative
    # These ceilings must originate in a future trusted host/provider adapter.
    token_ceiling: Positive | None = None
    usd_ceiling: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    duration_ceiling_ms: Positive | None = None
    retry: bool = False


class PlannedPair(Contract):
    identity: Hash
    scenario: Hash
    first_arm: Arm
    ordinal: Positive
    development_slot: Identifier | None = None


class PlannedCluster(Contract):
    identity: Hash
    scenarios: list[Hash] = Field(min_length=1, max_length=500)
    pairs: list[PlannedPair] = Field(min_length=2, max_length=500)


class ConfirmatoryAllocation(Artifact):
    kind: Literal["benchmark_allocation"] = "benchmark_allocation"
    allocation_version: Literal["confirmatory_allocation_v1"] = "confirmatory_allocation_v1"
    supersedes: Reference | None = None
    protocol: Reference
    plan: Reference
    catalog: Reference
    source: Literal["sealed_held_out", "synthetic_development"]
    audit_hash: Hash | None
    power_design_hash: Hash
    seed: Nonnegative
    clusters: list[PlannedCluster] = Field(min_length=1, max_length=500)
    cluster_count: Annotated[int, Field(ge=1, le=500)]
    repetitions_per_cluster: Annotated[int, Field(ge=2, le=40, multiple_of=2)]
    planned_pairs: Positive
    target_power: Literal[0.8, 0.9] = 0.8
    budget: FutureBudget | None = None

    @model_validator(mode="after")
    def verify_shape(self) -> Self:
        sealed = self.source == "sealed_held_out"
        if sealed != (self.audit_hash is not None):
            raise ValueError("sealed allocation requires an audit fingerprint")
        if (
            self.cluster_count != len(self.clusters)
            or self.planned_pairs != self.cluster_count * self.repetitions_per_cluster
            or len({cluster.identity for cluster in self.clusters}) != self.cluster_count
        ):
            raise ValueError("allocation cluster or planned pair count mismatch")
        case_ids, pair_ids, slots = set(), set(), set()
        for cluster in self.clusters:
            if case_ids.intersection(cluster.scenarios) or len(set(cluster.scenarios)) != len(
                cluster.scenarios
            ):
                raise ValueError("scenario appears in multiple cluster memberships")
            if (
                len(cluster.pairs) != self.repetitions_per_cluster
                or [pair.ordinal for pair in cluster.pairs]
                != list(range(1, len(cluster.pairs) + 1))
                or sum(pair.first_arm == "baseline" for pair in cluster.pairs)
                != self.repetitions_per_cluster // 2
            ):
                raise ValueError("allocation has missing, duplicate or unbalanced slots")
            for pair in cluster.pairs:
                slot = pair.development_slot
                if (
                    pair.scenario not in cluster.scenarios
                    or pair.identity in pair_ids
                    or sealed != (slot is None)
                    or slot is not None
                    and slot in slots
                ):
                    raise ValueError("allocation pair repeats an identity or leaves its membership")
                pair_ids.add(pair.identity)
                if slot is not None:
                    slots.add(slot)
            case_ids.update(cluster.scenarios)
        return self


class EvidenceSelection(Contract):
    benchmark_result: Reference | None = None
    partial_run: Reference | None = None
    selected_reports: dict[str, UUID] = Field(default_factory=dict)

    @model_validator(mode="after")
    def explicit_source(self) -> Self:
        if (
            self.benchmark_result
            and self.partial_run
            or self.selected_reports
            and not self.partial_run
        ):
            raise ValueError("provide a complete result or a partial run with exact reports")
        return self


class ConfirmatoryAnalysis(Artifact):
    kind: Literal["benchmark_confirmatory_analysis"] = "benchmark_confirmatory_analysis"
    supersedes: Reference | None = None
    allocation: Reference
    evidence: EvidenceSelection
    producer_python_version: Annotated[str, Field(pattern=r"^3\.(11|12)\.\d+$")]
    report: dict
    result_hash: Hash


CONTRACTS = {
    model.model_fields["kind"].default: model
    for model in (ConfirmatoryAllocation, ConfirmatoryAnalysis)
}
