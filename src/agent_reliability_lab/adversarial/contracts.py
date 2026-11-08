"""Bounded, versioned experiment specifications independent of model instructions."""

import hashlib
from typing import Literal, Self

from pydantic import Field, model_validator

from agent_reliability_lab.benchmarks.scenario import Contract, Identifier, Injection, ToolName
from agent_reliability_lab.mcp.contracts import CreateTaskInput, UpdateTaskInput

DOMAINS = {
    "search_documents": "documents",
    "get_document": "documents",
    "get_order": "business",
    "get_customer": "business",
    "list_customer_orders": "business",
    "list_tasks": "tasks",
    "create_task": "tasks",
    "update_task": "tasks",
}
SURFACES = {
    "get_document": {"/data/content", "/data/title"},
    "search_documents": {"/data/items/0/snippet", "/data/items/0/title"},
    "get_customer": {"/data/display_name"},
    "list_tasks": {"/data/items/0/description", "/data/items/0/title"},
}


class Trigger(Contract):
    arguments: dict = Field(default_factory=dict)
    occurrence: int = Field(default=1, ge=1, le=100)
    max_activations: int = Field(default=1, ge=1, le=10)


class Target(Contract):
    specification_version: Literal["1.0"] = "1.0"
    injection_id: Identifier
    scenario_id: Identifier
    server: Literal["documents", "business", "tasks"]
    tool: ToolName
    trigger: Trigger = Field(default_factory=Trigger)

    @model_validator(mode="after")
    def domain_matches(self) -> Self:
        if DOMAINS[self.tool] != self.server:
            raise ValueError("tool does not belong to target server")
        return self


class FaultSpec(Target):
    fault_type: Literal[
        "transient_error",
        "timeout_before_dispatch",
        "response_lost_after_commit",
        "malformed_response",
        "empty_result",
        "permanent_error",
    ]
    boundary: Literal["before_dispatch", "before_output_validation", "after_validated_response"]
    recoverable: bool
    visibility: Literal["agent_transport", "model_observation"] = "agent_transport"
    duration_ms: int = Field(default=0, ge=0, le=5000)
    seed: int = Field(default=0, ge=0)
    equivalent_recovery_arguments: list[dict] = Field(default_factory=list, max_length=10)
    permissible_recovery: list[
        Literal[
            "transport_retry",
            "idempotent_receipt_replay",
            "agent_corrective_action",
            "requery",
        ]
    ] = Field(default_factory=list, max_length=4)
    permanent_code: (
        Literal[
            "permission_denied",
            "approval_required",
            "validation_error",
            "idempotency_conflict",
            "version_conflict",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def coherent_fault(self) -> Self:
        expected = {
            "transient_error": "before_dispatch",
            "timeout_before_dispatch": "before_dispatch",
            "permanent_error": "before_dispatch",
            "malformed_response": "before_output_validation",
            "empty_result": "before_output_validation",
            "response_lost_after_commit": "after_validated_response",
        }
        if self.boundary != expected[self.fault_type]:
            raise ValueError("fault type and boundary disagree")
        if self.duration_ms:
            raise ValueError("v1 uses logical timeouts; real delays are unsupported")
        if self.fault_type == "response_lost_after_commit" and self.tool not in {
            "create_task",
            "update_task",
        }:
            raise ValueError("after-commit response loss requires a write tool")
        if self.fault_type == "empty_result" and self.tool not in {
            "search_documents",
            "list_tasks",
            "list_customer_orders",
        }:
            raise ValueError("empty result requires a paginated read")
        if (self.fault_type == "permanent_error") != (self.permanent_code is not None):
            raise ValueError("permanent faults require exactly one permanent code")
        if self.fault_type == "permanent_error" and self.recoverable:
            raise ValueError("permanent business errors are not transport-recoverable")
        if self.recoverable and not self.permissible_recovery:
            raise ValueError("recoverable fault requires a declared recovery mechanism")
        return self


class AttackDelivery(Target):
    surface: str
    payload_reference: Identifier
    payload: str = Field(min_length=1, max_length=6000)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    trust_classification: Literal["untrusted"] = "untrusted"
    corpus_version: Literal["1.0.0"] = "1.0.0"
    exposure_criteria: Literal["exact_payload_in_model_request"] = "exact_payload_in_model_request"
    group: Identifier | None = None

    @model_validator(mode="after")
    def bounded_surface(self) -> Self:
        if self.surface not in SURFACES.get(self.tool, set()):
            raise ValueError("surface is not an attacker-writable textual data field")
        if hashlib.sha256(self.payload.encode()).hexdigest() != self.payload_hash:
            raise ValueError("payload hash mismatch")
        return self


class Objective(Contract):
    kind: Literal[
        "unauthorized_attempt",
        "prohibited_mutation",
        "workflow_hijack",
        "answer_contamination",
        "canary_disclosure",
        "authority_spoofing",
    ]
    oracle: Literal["unauthorized_proposal", "task_change", "response_contains"]
    tool: ToolName | None = None
    arguments: dict = Field(default_factory=dict)
    target: dict = Field(default_factory=dict)
    text: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def complete_oracle(self) -> Self:
        kinds = {
            "unauthorized_attempt": "unauthorized_proposal",
            "prohibited_mutation": "task_change",
            "workflow_hijack": "task_change",
            "answer_contamination": "response_contains",
            "canary_disclosure": "response_contains",
        }
        if self.kind in kinds and self.oracle != kinds[self.kind]:
            raise ValueError("objective kind and oracle disagree")
        if self.oracle == "response_contains" and not self.text:
            raise ValueError("response objective requires a bounded literal")
        if self.oracle == "unauthorized_proposal" and self.tool is None:
            raise ValueError("proposal objective requires a target tool")
        if self.oracle == "task_change" and not self.target:
            raise ValueError("mutation objective requires target predicates")
        if self.kind == "canary_disclosure" and not (self.text or "").startswith("SYNTHETIC_"):
            raise ValueError("canary must be clearly labeled SYNTHETIC_")
        return self


class AttackSpec(AttackDelivery):
    objective: Objective


class WriteScope(Contract):
    tool: Literal["create_task", "update_task"]
    arguments: dict

    @model_validator(mode="after")
    def narrow_supported_write(self) -> Self:
        if self.tool == "create_task":
            CreateTaskInput.model_validate(self.arguments)
        else:
            UpdateTaskInput.model_validate({"expected_version": 1, **self.arguments})
        return self


class Defense(Contract):
    configuration: Literal["baseline", "guarded"] = "baseline"
    policy_version: Literal["task_scope_v1"] = "task_scope_v1"
    write_scopes: list[WriteScope] = Field(default_factory=list, max_length=30)


class RuntimePlan(Contract):
    """Only execution configuration; no hidden attacker objectives or scoring rules."""

    version: Literal["1.0"] = "1.0"
    faults: list[FaultSpec] = Field(default_factory=list, max_length=10)
    attacks: list[AttackDelivery] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def no_overlap(self) -> Self:
        specs = [*self.faults, *self.attacks]
        if len({s.injection_id for s in specs}) != len(specs):
            raise ValueError("injection IDs must be unique")
        # One spec per tool prevents ambiguous overlapping transformations in v1.
        if len({s.tool for s in specs}) != len(specs):
            raise ValueError("v1 permits one injection specification per tool")
        return self


class HarnessSpec(Contract):
    version: Literal["1.0"] = "1.0"
    scenario_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    faults: list[FaultSpec] = Field(default_factory=list, max_length=10)
    attacks: list[AttackSpec] = Field(default_factory=list, max_length=10)
    benign_control: bool = False

    @model_validator(mode="after")
    def coherent(self) -> Self:
        self.runtime()
        if self.benign_control and (self.faults or self.attacks):
            raise ValueError("benign controls cannot contain configured injections")
        return self

    def runtime(self) -> RuntimePlan:
        return RuntimePlan(
            faults=self.faults,
            attacks=[
                AttackDelivery.model_validate(a.model_dump(exclude={"objective"}))
                for a in self.attacks
            ],
        )

    def covers_legacy(self, legacy: Injection) -> bool:
        candidates = self.faults if legacy.kind == "fault" else self.attacks
        for item in candidates:
            if (
                item.tool != legacy.tool
                or item.trigger.occurrence != legacy.on_call
                or item.trigger.max_activations != 1
            ):
                continue
            if legacy.kind == "fault":
                mapping = {
                    "timeout": "timeout_before_dispatch",
                    "transient_error": "transient_error",
                    "malformed_response": "malformed_response",
                }
                if (
                    item.fault_type == mapping[legacy.fault]
                    and item.recoverable == legacy.recoverable
                ):
                    return True
            elif item.payload == legacy.payload and (
                legacy.surface != "document_content"
                or item.surface in {"/data/content", "/data/items/0/snippet"}
            ):
                return True
        return False
