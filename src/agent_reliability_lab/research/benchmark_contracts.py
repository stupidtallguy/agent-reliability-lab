"""Versioned CP12 contracts layered over the existing scenario and research records."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from agent_reliability_lab.adversarial.contracts import HarnessSpec, WriteScope
from agent_reliability_lab.agent.config import Budgets, ModelConfig
from agent_reliability_lab.benchmarks.scenario import Contract, Identifier, Text
from agent_reliability_lab.evaluation.contracts import Case, SourceMethod
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.contracts import Artifact, Reference

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Version = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
UUID = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
Family = Literal["tool_use", "policy_resilience", "external_recovery"]
Partition = Literal["training", "development", "held_out"]
FAMILIES = ("tool_use", "policy_resilience", "external_recovery")
MULTIFAMILY_INTERVENTION = "guard_multifamily_v1"
QUALIFICATION_INTERVENTION = "guard_single_pair_qualification_v1"
MULTIBLOCK_INTERVENTION = "guard_multiblock_qualification_v1"
CROSS_TEMPLATE_INTERVENTION = "guard_cross_template_qualification_v1"
OUTCOMES = (
    "task_success",
    "attack_success",
    "unauthorized_attempt",
    "prohibited_effect",
    "correct_refusal",
    "false_refusal",
    "recovery",
    "duplicate_effect",
    "evidence_complete",
)


class RefusalRubric(Contract):
    expected: Literal["required", "prohibited"]
    phrases: list[Annotated[str, Field(min_length=4, max_length=200)]] = Field(
        min_length=1, max_length=12
    )


class BenchmarkCase(Contract):
    case: Case
    family: Family
    template_id: Identifier
    template_family: Identifier
    attack_family: Identifier | None = None
    partition: Partition
    benchmark_version: Version
    harness: HarnessSpec
    write_scopes: list[WriteScope] = Field(default_factory=list, max_length=30)
    refusal: RefusalRubric | None = None

    @property
    def scenario_id(self):
        return self.case.scenario.scenario_id

    @property
    def scenario_hash(self):
        return digest(self.case.scenario.model_dump(mode="json"))

    @model_validator(mode="after")
    def bind_case(self) -> Self:
        scenario = self.case.scenario
        if scenario.metadata.split != (
            "held_out" if self.partition == "held_out" else "development"
        ):
            raise ValueError("benchmark partition conflicts with the scenario split")
        if self.harness.scenario_hash != self.scenario_hash or (
            self.case.oracle.scenario_hash != self.scenario_hash
        ):
            raise ValueError("harness and oracle must pin the exact scenario hash")
        targets = [*self.harness.attacks, *self.harness.faults]
        if any(
            target.scenario_id != self.scenario_id or target.tool not in scenario.tools.available
            for target in targets
        ) or not all(self.harness.covers_legacy(declared) for declared in scenario.injections):
            raise ValueError("harness targets do not match the frozen scenario")
        if bool(self.harness.attacks) != (self.attack_family is not None):
            raise ValueError("attack cases require an explicit attack family")
        if any(scope.tool not in scenario.tools.permitted for scope in self.write_scopes):
            raise ValueError("guarded scope exceeds the scenario tool permissions")
        return self

    def partition_keys(self):
        keys = [
            ("scenario", self.scenario_id),
            ("stimulus", self.stimulus_hash()),
            ("template", self.template_id),
            ("template_family", self.template_family),
            *(("attack_payload", item.payload_hash) for item in self.harness.attacks),
        ]
        if self.attack_family is not None:
            keys.append(("attack_family", self.attack_family))
        return keys

    def stimulus_hash(self):
        # Cosmetic labels, budgets and oracle changes cannot make an input independent.
        scenario = self.case.scenario.model_dump(mode="json")
        fixture = {k: v for k, v in scenario["fixture"].items() if k not in {"fixture_id", "seed"}}
        runtime = self.harness.runtime().model_dump(mode="json")
        injections = [
            {
                k: v
                for k, v in entry.items()
                if k not in {"injection_id", "scenario_id", "seed", "payload_reference", "group"}
            }
            for entry in [*runtime["faults"], *runtime["attacks"]]
        ]
        return digest(
            {
                "user_request": scenario["user_request"],
                "actor": scenario["actor"],
                "tools": {key: sorted(value) for key, value in scenario["tools"].items()},
                "fixture": {
                    key: sorted(value, key=digest) if isinstance(value, list) else value
                    for key, value in fixture.items()
                },
                "runtime": sorted(injections, key=digest),
            }
        )


class BenchmarkDataset(Artifact):
    kind: Literal["benchmark_dataset"] = "benchmark_dataset"
    validation: Literal["template_attack_disjoint_v1"] = "template_attack_disjoint_v1"
    benchmark_version: Version
    family_versions: dict[Family, Version]
    cases: list[BenchmarkCase] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def disjoint(self) -> Self:
        if set(self.family_versions) != set(FAMILIES):
            raise ValueError("each task family requires a version")
        seen, stimuli = set(), set()
        assignments = {}
        for item in self.cases:
            if item.benchmark_version != self.benchmark_version:
                raise ValueError("inconsistent benchmark version")
            content = item.stimulus_hash()
            if item.scenario_id in seen or content in stimuli:
                raise ValueError("duplicate scenario identity or executable definition")
            seen.add(item.scenario_id)
            stimuli.add(content)
            for key in item.partition_keys():
                if assignments.setdefault(key, item.partition) != item.partition:
                    raise ValueError(f"{key[0]} crosses benchmark partitions")
        return self


class StatisticalPlan(Contract):
    method: Literal["paired_template_cluster_bootstrap_v1"] = "paired_template_cluster_bootstrap_v1"
    interval_level: Literal[0.95] = 0.95
    resamples: int = Field(default=2000, ge=100, le=10000)
    bootstrap_seed: int = Field(default=0, ge=0)


class BenchmarkProtocol(Artifact):
    kind: Literal["benchmark_protocol"] = "benchmark_protocol"
    mode: Literal["synthetic_exploratory", "provider_development_exploratory"] = (
        "synthetic_exploratory"
    )
    benchmark_version: Version
    dataset: Reference
    supersedes: Reference | None = None
    scenarios: list[Identifier] = Field(min_length=1, max_length=100)
    scripts: dict[Identifier, list[dict]]
    hypothesis: Text
    threat_model: Text
    primary_outcome: Literal["task_success"] = "task_success"
    secondary_outcomes: list[str] = Field(default_factory=lambda: list(OUTCOMES[1:]))
    repetitions: int = Field(ge=1, le=20)
    planned_pairs: int = Field(ge=1, le=500)
    allocation_rationale: Text
    order_seed: int = Field(ge=0)
    arms: tuple[Literal["baseline"], Literal["guarded"]] = ("baseline", "guarded")
    intervention: Literal[
        "task_scope_and_observation_framing_v1",
        "guard_factorial_v1",
        "guard_multifamily_v1",
        "guard_single_pair_qualification_v1",
        "guard_multiblock_qualification_v1",
        "guard_cross_template_qualification_v1",
    ] = "task_scope_and_observation_framing_v1"
    model: ModelConfig
    transport: Literal["memory", "stdio"] = "memory"
    evaluator_version: Literal["1.7.0"] = "1.7.0"
    source_commit: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    source_method: SourceMethod | None = Field(default=None, exclude_if=lambda value: value is None)
    source_hash: Hash
    lock_hash: Hash
    budgets: Budgets
    statistics: StatisticalPlan = Field(default_factory=StatisticalPlan)
    exclusion_rule: Literal["frozen_capture_and_comparable_complete_pairs_v1"] = (
        "frozen_capture_and_comparable_complete_pairs_v1"
    )

    @model_validator(mode="after")
    def valid_plan(self) -> Self:
        qualification = self.intervention == QUALIFICATION_INTERVENTION
        cross_template = self.intervention == CROSS_TEMPLATE_INTERVENTION
        scenario_counts = (
            (4, 10)
            if self.intervention == MULTIFAMILY_INTERVENTION
            else (4 if cross_template else 1,)
        )
        if len(set(self.scenarios)) != len(self.scenarios):
            raise ValueError("select unique development scenarios")
        if self.mode == "synthetic_exploratory" and set(self.scripts) != set(self.scenarios):
            raise ValueError("select unique scenarios with exactly one script per scenario")
        if self.mode == "provider_development_exploratory" and (
            self.scripts
            or len(self.scenarios) not in scenario_counts
            or self.repetitions != (1 if qualification or cross_template else 2)
            or self.model.provider not in {"openai", "groq", "ollama"}
        ):
            raise ValueError(
                "provider feasibility requires the registered development pair schedule"
            )
        if any(not script or len(script) > 100 for script in self.scripts.values()):
            raise ValueError("each scripted scenario requires a bounded nonempty plan")
        factorial = self.intervention == "guard_factorial_v1"
        if (
            factorial
            or qualification
            or cross_template
            or self.intervention in {MULTIFAMILY_INTERVENTION, MULTIBLOCK_INTERVENTION}
        ) and (self.model.provider != "ollama" or self.mode != "provider_development_exploratory"):
            raise ValueError("guard ablation is available only to local development")
        if self.planned_pairs != len(self.scenarios) * self.repetitions * (4 if factorial else 1):
            raise ValueError("planned pair count differs from the allocation")
        if self.secondary_outcomes != list(OUTCOMES[1:]):
            raise ValueError("unsupported secondary outcome contract")
        if (
            (self.mode == "synthetic_exploratory" and self.model.provider != "fake")
            or self.model.script
            or self.model.repeat_last
        ):
            raise ValueError("CP12 accepts only the fixed per-scenario scripted model")
        if any(
            x is not None
            for x in (
                self.budgets.max_known_tokens,
                self.budgets.max_estimated_cost,
                self.budgets.price_schedule,
            )
        ):
            raise ValueError("scripted execution has no live token or price schedule")
        if (self.version == 1) != (self.supersedes is None):
            raise ValueError("protocol amendments must pin their immediate predecessor")
        if self.supersedes and (
            self.supersedes.kind,
            self.supersedes.identity,
            self.supersedes.version,
        ) != (self.kind, self.identity, self.version - 1):
            raise ValueError("protocol predecessor identity or version differs")
        return self


class BenchmarkRun(Artifact):
    kind: Literal["benchmark_run"] = "benchmark_run"
    version: Literal[1] = 1
    protocol: Reference
    schedule_hash: Hash
    allocation: Reference | None = Field(default=None, exclude_if=lambda value: value is None)
    pilot: Reference | None = Field(default=None, exclude_if=lambda value: value is None)
    live_authorization: Reference | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class BenchmarkResult(Artifact):
    kind: Literal["benchmark_result"] = "benchmark_result"
    version: Literal[1] = 1
    run: Reference
    evaluator_reports: dict[str, UUID]
    result_hash: Hash
    result: dict


class BenchmarkBlockEvent(Artifact):
    kind: Literal["benchmark_block_event"] = "benchmark_block_event"
    policy: Literal["local_memory_blocks_v1"] = "local_memory_blocks_v1"
    run: Reference
    slot: Identifier
    arm: Literal["baseline", "guarded"]
    action: Literal["claim", "capture", "memory_stop"]
    available_bytes: int | None = Field(default=None, ge=0)
    report_id: UUID | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.identity != self.run.identity or self.run.kind != "benchmark_run":
            raise ValueError("block event must identify its frozen run")
        if (self.report_id is not None) != (self.action == "capture"):
            raise ValueError("only a capture pins an evaluator report")
        return self


CONTRACTS = {
    model.model_fields["kind"].default: model
    for model in (
        BenchmarkDataset,
        BenchmarkProtocol,
        BenchmarkRun,
        BenchmarkResult,
        BenchmarkBlockEvent,
    )
}
