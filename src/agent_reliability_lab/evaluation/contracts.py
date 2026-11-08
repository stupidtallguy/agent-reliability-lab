"""Versioned evaluation sidecars leave the original Scenario v1 contract intact."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from agent_reliability_lab.adversarial.contracts import HarnessSpec, WriteScope
from agent_reliability_lab.agent.config import Budgets, ModelConfig
from agent_reliability_lab.benchmarks.scenario import Contract, Identifier, Scenario, StateChange

Outcome = Literal[
    "successful",
    "incorrect_final_state",
    "missing_required_action",
    "forbidden_side_effect",
    "incorrect_response",
    "agent_execution_failure",
    "budget_exhausted",
    "authorization_failure",
    "incomplete_execution",
    "invalid_scenario",
    "evidence_error",
    "infrastructure_failure",
    "not_executed",
]
FailureLabel = Literal[
    "incorrect_tool_selection",
    "incorrect_tool_arguments",
    "missing_required_tool_call",
    "unnecessary_tool_call",
    "tool_execution_failure",
    "authorization_denial",
    "incorrect_state_mutation",
    "forbidden_side_effect",
    "duplicate_operation",
    "recovery_failure",
    "incorrect_final_answer",
    "budget_exhaustion",
    "incomplete_execution",
    "incomplete_evidence",
    "infrastructure_failure",
    "invalid_scenario",
    "missing_required_change",
    "premature_completion",
    "context_observation_handling_failure",
    "model_execution_failure",
]


class Finding(Contract):
    label: FailureLabel
    detail: str
    references: list[str] = Field(default_factory=list)


class RequiredChange(Contract):
    rule_id: Identifier
    entity: Literal["tasks", "orders", "customers", "payments", "accounts", "documents"]
    operation: Literal["create", "update", "delete"]
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)
    minimum: int = Field(default=1, ge=0)
    maximum: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("maximum must be at least minimum")
        return self


class ResponseFacts(Contract):
    """Each group requires one bounded literal phrase; no executable regex/code."""

    rule_id: Identifier
    any_of: list[list[str]] = Field(min_length=1, max_length=30)
    forbidden: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def bounded_phrases(self) -> Self:
        if any(not group for group in self.any_of):
            raise ValueError("response groups cannot be empty")
        if any(
            not text.strip() or len(text) > 200
            for text in [*self.forbidden, *(text for group in self.any_of for text in group)]
        ):
            raise ValueError("response phrases must contain 1-200 characters")
        return self


class ToolRule(Contract):
    rule_id: Identifier
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict = Field(default_factory=dict)
    minimum: int = Field(default=0, ge=0)
    maximum: int | None = Field(default=None, ge=0)
    after_tools: list[str] = Field(default_factory=list)
    allow_retries: bool = True

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("maximum must be at least minimum")
        return self


class OracleSpec(Contract):
    schema_version: Literal["1.0"] = "1.0"
    annotation_version: str = Field(default="1.0.0", min_length=1, max_length=64)
    scenario_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    required_changes: list[RequiredChange] = Field(default_factory=list)
    response_facts: list[ResponseFacts] = Field(default_factory=list)
    tool_rules: list[ToolRule] | None = None
    # Sidecars may add tests, never weaken the legacy allowed/forbidden rules.
    forbidden_changes: list[StateChange] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_rules(self) -> Self:
        rules = [*self.required_changes, *self.response_facts, *(self.tool_rules or [])]
        if len({rule.rule_id for rule in rules}) != len(rules):
            raise ValueError("rule IDs must be unique")
        return self


class ModelPrice(Contract):
    provider: str
    model_id: str
    effective_from: AwareDatetime
    effective_until: AwareDatetime | None = None
    provenance: str = Field(min_length=1, max_length=1000)
    units: Literal["per_million_tokens"] = "per_million_tokens"
    mapping: Literal["openai_chat_inclusive_v1"] = "openai_chat_inclusive_v1"
    input_rate: Decimal = Field(ge=0, allow_inf_nan=False)
    output_rate: Decimal = Field(ge=0, allow_inf_nan=False)
    cached_input_rate: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    fixed_request_fee: Decimal = Field(default=Decimal("0"), ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def dates(self) -> Self:
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("price effective_until must follow effective_from")
        return self


class PriceBook(Contract):
    schema_version: Literal["1.0"] = "1.0"
    version: str
    currency: Literal["USD"] = "USD"
    prices: list[ModelPrice]

    @model_validator(mode="after")
    def no_overlaps(self) -> Self:
        for index, price in enumerate(self.prices):
            for other in self.prices[index + 1 :]:
                if (price.provider, price.model_id) == (other.provider, other.model_id):
                    if (
                        price.effective_until is None
                        or other.effective_from < price.effective_until
                    ) and (
                        other.effective_until is None
                        or price.effective_from < other.effective_until
                    ):
                        raise ValueError("price intervals for a model cannot overlap")
        return self


class ExperimentConfig(Contract):
    schema_version: Literal["1.0"] = "1.0"
    configuration_id: Identifier = "development_default"
    repeats: int = Field(default=1, ge=1, le=100)
    model: ModelConfig = Field(default_factory=ModelConfig)
    transport: Literal["stdio", "memory"] = "stdio"
    budgets: Budgets = Field(default_factory=Budgets)
    scripts: dict[str, list[dict]] = Field(default_factory=dict)
    annotations: dict[str, OracleSpec] = Field(default_factory=dict)
    prices: PriceBook | None = None
    source_commit: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    accounting_limits: Literal["posthoc_usage_cost_v1"] = "posthoc_usage_cost_v1"
    harnesses: dict[str, HarnessSpec] = Field(default_factory=dict)
    defense: Literal["baseline", "guarded"] = "baseline"
    write_scopes: dict[str, list[WriteScope]] = Field(default_factory=dict)
    pairing_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class Exposure(Contract):
    kind: Literal["fault", "attack"]
    tool: str
    attempt_id: str
    recoverable: bool = False
    source_reference: str


class Evidence(Contract):
    schema_version: Literal["1.0"] = "1.0"
    execution_id: str
    sandbox_run_id: str
    marker: str
    seed_hash: str
    fixture_hash: str
    initial_hash: str
    initial: dict
    final: dict
    initial_full: dict
    final_full: dict
    execution: dict
    tool_access: dict = Field(default_factory=dict)
    catalog: list[dict] = Field(default_factory=list)
    events: list[dict]
    operations: list[dict]
    attempts: list[dict]
    requests: list[dict]
    receipts: list[dict]
    audits: list[dict]
    source_hashes: dict[str, str]
    observed_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    timing_complete: bool = True
    exposures: list[Exposure] = Field(default_factory=list)
    experimental: dict | None = Field(default=None, exclude_if=lambda value: value is None)


class CallAssessment(Contract):
    proposal_id: str
    attempt_id: str | None
    tool: str
    status: Literal["valid", "invalid", "unnecessary", "unscorable"]
    reason: str
    unauthorized: bool | None
    executed: bool | None
    logical_operation_id: str | None = None
    reference: str


class EvaluationResult(Contract):
    schema_version: Literal["1.0"] = "1.0"
    evaluator_version: str
    scoring_id: str
    trial_id: str
    experiment_id: str
    execution_id: str | None
    scenario_id: str
    scenario_version: int
    scenario_hash: str
    category: str
    split: str
    trial_index: int
    mode: Literal["scripted", "live"]
    status: Outcome
    objective_success: bool | None
    eligible: bool
    exclusion_reason: str | None = None
    agent_status: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    checks: list[dict] = Field(default_factory=list)
    calls: list[CallAssessment] = Field(default_factory=list)
    reconciliation: dict = Field(default_factory=dict)
    unsafe: bool | None = None
    unauthorized_attempt: bool | None = None
    recovery_eligible: bool = False
    recovered: bool | None = None
    attack_eligible: bool = False
    attacker_success: bool | None = None
    duration_seconds: float | None = None
    timing_complete: bool = False
    tool_proposals: int = 0
    tool_attempts: int = 0
    retry_count: int = 0
    usage: dict = Field(default_factory=dict)
    cost: dict = Field(default_factory=dict)
    evidence_hash: str | None = None
    evidence_reference: str | None = None
    rules_hash: str
    oracle_spec: dict = Field(default_factory=dict)
    accounting_checks: dict = Field(default_factory=dict)
    scoring_provenance: dict = Field(default_factory=dict)
    scored_at: datetime
    warnings: list[str] = Field(default_factory=list)
    experimental: dict = Field(default_factory=dict, exclude_if=lambda value: not value)


class Case(Contract):
    """An optional wrapper; original benchmark files remain plain Scenario v1."""

    scenario: Scenario
    oracle: OracleSpec = Field(default_factory=OracleSpec)
