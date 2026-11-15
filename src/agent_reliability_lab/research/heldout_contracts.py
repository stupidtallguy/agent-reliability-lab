"""Content-free registrable CP13 records and an external-only stimulus schema."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from agent_reliability_lab.benchmarks.scenario import Contract, Identifier, Text
from agent_reliability_lab.research.benchmark_contracts import (
    OUTCOMES,
    BenchmarkCase,
    Hash,
    Version,
)
from agent_reliability_lab.research.contracts import Artifact, Reference

PRIVATE_FORMAT = "opsdesk_private_heldout_v1"
Coverage = Literal[
    "tool_selection",
    "authorization",
    "prompt_injection",
    "unauthorized_operation",
    "recovery",
    "idempotency",
    "partial_execution",
    "multi_step",
    "conflicting_instructions",
    "infrastructure_failure",
]


class PrivateCase(Contract):
    scenario: BenchmarkCase
    origin: Literal["private_authored", "synthetic_fixture"]
    source: Identifier
    lineage: list[Identifier] = Field(default_factory=list, max_length=30)
    coverage: list[Coverage] = Field(min_length=1, max_length=10)


class PrivateCatalog(Contract):
    format: Literal[PRIVATE_FORMAT] = PRIVATE_FORMAT
    benchmark_version: Version
    nonce: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    cases: list[PrivateCase] = Field(min_length=1, max_length=500)


class LeakagePolicy(Contract):
    audit_version: Literal["1.0.0"] = "1.0.0"
    lexical_threshold: float = Field(default=0.8, ge=0.5, le=1)
    structural_threshold: float = Field(default=0.92, ge=0.5, le=1)
    minimum_lexical_tokens: int = Field(default=6, ge=3, le=30)
    disposition: Literal["exclude_all_flagged_and_fail_catalog"] = (
        "exclude_all_flagged_and_fail_catalog"
    )


class CatalogSeal(Artifact):
    kind: Literal["benchmark_catalog_seal"] = "benchmark_catalog_seal"
    benchmark_version: Version
    reference_dataset: Reference
    comparison_hash: Hash
    artifact_sha256: Hash
    held_out_count: int = Field(ge=1, le=500)


class PowerScenario(Contract):
    identity: Identifier
    rationale: Text
    expected_difference: float = Field(gt=0, lt=1)
    discordance: float = Field(gt=0, le=1)
    cluster_sign_icc: float = Field(ge=0, lt=1)
    repetitions_per_cluster: int = Field(ge=2, le=40, multiple_of=2)
    pair_missing: float = Field(ge=0, lt=1)
    pair_excluded: float = Field(ge=0, lt=1)
    cluster_dropout: float = Field(ge=0, lt=1)

    @model_validator(mode="after")
    def feasible(self) -> Self:
        if self.expected_difference >= self.discordance:
            raise ValueError("expected difference must be smaller than discordance")
        if self.pair_missing + self.pair_excluded >= 1:
            raise ValueError("pair loss probabilities must sum to less than one")
        return self


class PowerDesign(Contract):
    schema_version: Literal["1.0"] = "1.0"
    alpha: float = Field(default=0.05, ge=0.01, le=0.10)
    seed: int = Field(default=34917, ge=0, le=2**63 - 1)
    simulations: int = Field(default=2000, ge=100, le=10000)
    minimum_meaningful_difference: float | None = Field(default=None, gt=0, lt=1)
    planning_basis: Literal["illustrative", "externally_justified"] = "illustrative"
    justification: Text | None = None
    cluster_grid: list[Annotated[int, Field(ge=20, le=1500)]] = Field(
        default_factory=lambda: [20, 40, 60, 80, 120, 160, 240, 320, 480],
        min_length=1,
        max_length=24,
    )
    maximum_null_inflation: float = Field(default=0.02, ge=0, le=0.03)
    scenarios: list[PowerScenario] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def valid_design(self) -> Self:
        if self.cluster_grid != sorted(set(self.cluster_grid)):
            raise ValueError("candidate cluster counts must be strictly increasing")
        if len({row.identity for row in self.scenarios}) != len(self.scenarios):
            raise ValueError("power scenario identities must be unique")
        draws = (
            2
            * self.simulations
            * self.cluster_grid[-1]
            * sum(row.repetitions_per_cluster for row in self.scenarios)
        )
        if draws > 80_000_000:
            raise ValueError("simulation grid exceeds the bounded planning workload")
        return self


class ConfirmatoryProtocol(Artifact):
    kind: Literal["benchmark_confirmatory_protocol"] = "benchmark_confirmatory_protocol"
    catalog: Reference
    development_protocol: Reference
    supersedes: Reference | None = None
    power: PowerDesign = Field(default_factory=PowerDesign)
    leakage: LeakagePolicy = Field(default_factory=LeakagePolicy)
    order_seed: int = Field(default=42, ge=0, le=2**63 - 1)
    execution: Literal["disabled_planning_only"] = "disabled_planning_only"


class ConfirmatoryAnalysisPlan(Artifact):
    kind: Literal["benchmark_analysis_plan"] = "benchmark_analysis_plan"
    protocol: Reference
    catalog: Reference
    supersedes: Reference | None = None
    analysis_version: Literal["1.0.0"] = "1.0.0"
    estimand: Literal["equal_template_cluster_mean_guarded_minus_baseline"] = (
        "equal_template_cluster_mean_guarded_minus_baseline"
    )
    primary_outcome: Literal["task_success"] = "task_success"
    secondary_outcomes: list[str] = Field(default_factory=lambda: list(OUTCOMES[1:]))
    sampling_unit: Literal["independent_template_family"] = "independent_template_family"
    weighting: Literal["equal_cluster_equal_arm_order"] = "equal_cluster_equal_arm_order"
    paired_method: Literal["two_sided_student_t_on_cluster_differences"] = (
        "two_sided_student_t_on_cluster_differences"
    )
    interval: Literal["student_t_one_minus_alpha"] = "student_t_one_minus_alpha"
    missing_data: Literal["complete_pairs_each_order_with_planned_slot_bounds"] = (
        "complete_pairs_each_order_with_planned_slot_bounds"
    )
    exclusions: Literal["frozen_eligibility_infrastructure_integrity_and_indeterminate_v1"] = (
        "frozen_eligibility_infrastructure_integrity_and_indeterminate_v1"
    )
    multiplicity: Literal["one_primary_secondary_descriptive_only"] = (
        "one_primary_secondary_descriptive_only"
    )
    sensitivity: Literal["planned_slot_extremes_and_preregistered_power_grid"] = (
        "planned_slot_extremes_and_preregistered_power_grid"
    )
    software_version: Literal["opsdesk_cluster_design_1.0.0"] = "opsdesk_cluster_design_1.0.0"
    python_version: Annotated[str, Field(pattern=r"^3\.(11|12)\.\d+$")]
    alpha: float = Field(ge=0.01, le=0.10)
    simulation_seed: int = Field(ge=0)
    order_seed: int = Field(ge=0)

    @model_validator(mode="after")
    def fixed_outcomes(self) -> Self:
        if self.secondary_outcomes != list(OUTCOMES[1:]):
            raise ValueError("secondary outcomes must preserve the benchmark outcome contract")
        return self


CONTRACTS = {
    model.model_fields["kind"].default: model
    for model in (CatalogSeal, ConfirmatoryProtocol, ConfirmatoryAnalysisPlan)
}
