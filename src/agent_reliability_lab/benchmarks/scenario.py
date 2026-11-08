"""Validate synthetic scenario specifications, without executing tools or predicates."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")]
Text = Annotated[str, Field(min_length=1, max_length=10000)]
ToolName = Literal[
    "search_documents",
    "get_document",
    "get_order",
    "get_customer",
    "list_customer_orders",
    "list_tasks",
    "create_task",
    "update_task",
]
Category = Literal[
    "normal",
    "multi_step",
    "tool_failure",
    "prompt_injection",
    "authorization",
    "ambiguous",
]
Role = Literal["viewer", "support_agent", "supervisor"]


class Contract(BaseModel):
    """Reject misspelled fields and unintended scalar coercions."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Actor(Contract):
    actor_id: Identifier
    tenant_id: Identifier
    role: Role


class Document(Contract):
    document_id: Identifier
    tenant_id: Identifier
    title: Text
    content: Text


class Customer(Contract):
    customer_id: Identifier
    tenant_id: Identifier
    display_name: Text


class Order(Contract):
    order_id: Identifier
    customer_id: Identifier
    tenant_id: Identifier
    status: Literal["pending", "paid", "shipped", "cancelled"]


class Payment(Contract):
    payment_id: Identifier
    order_id: Identifier
    tenant_id: Identifier
    amount_cents: Annotated[int, Field(ge=0)]
    status: Literal["pending", "settled", "failed"]


class Account(Contract):
    account_id: Identifier
    customer_id: Identifier
    tenant_id: Identifier
    status: Literal["active", "suspended"]


class Task(Contract):
    task_id: Identifier
    tenant_id: Identifier
    customer_id: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    status: Literal["open", "in_progress", "resolved"]
    version: Annotated[int, Field(ge=1)] = 1


class EnvironmentFixture(Contract):
    """Inline fixtures are deterministic and require no external file resolution."""

    fixture_id: Identifier
    version: Literal["1.0"] = "1.0"
    seed: Annotated[int, Field(ge=0)]
    documents: list[Document] = Field(default_factory=list)
    customers: list[Customer] = Field(default_factory=list)
    orders: list[Order] = Field(default_factory=list)
    payments: list[Payment] = Field(default_factory=list)
    accounts: list[Account] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        for collection, key in [
            (self.documents, "document_id"),
            (self.customers, "customer_id"),
            (self.orders, "order_id"),
            (self.payments, "payment_id"),
            (self.accounts, "account_id"),
            (self.tasks, "task_id"),
        ]:
            identifiers = [getattr(item, key) for item in collection]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate {key} in fixture")
        customers = {item.customer_id: item for item in self.customers}
        orders = {item.order_id: item for item in self.orders}
        for record in [*self.orders, *self.accounts, *self.tasks]:
            customer = customers.get(record.customer_id)
            if customer is None or customer.tenant_id != record.tenant_id:
                raise ValueError("customer reference must exist in the same tenant")
        for payment in self.payments:
            order = orders.get(payment.order_id)
            if order is None or order.tenant_id != payment.tenant_id:
                raise ValueError("payment order reference must exist in the same tenant")
        return self


class ToolAccess(Contract):
    available: list[ToolName] = Field(min_length=1)
    permitted: list[ToolName]
    approval_required: list[ToolName] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_permissions(self) -> Self:
        for values in [self.available, self.permitted, self.approval_required]:
            if len(values) != len(set(values)):
                raise ValueError("tool lists must not contain duplicates")
        if not set(self.permitted) <= set(self.available):
            raise ValueError("permitted tools must be available")
        if not set(self.approval_required) <= set(self.permitted):
            raise ValueError("approval_required tools must be permitted")
        if set(self.approval_required) - {"create_task", "update_task"}:
            raise ValueError("approval gates are supported only for task writes")
        return self


class FaultInjection(Contract):
    kind: Literal["fault"]
    tool: ToolName
    on_call: Annotated[int, Field(ge=1)]
    fault: Literal["timeout", "transient_error", "malformed_response"]
    recoverable: bool


class AttackInjection(Contract):
    kind: Literal["attack"]
    tool: ToolName
    on_call: Annotated[int, Field(ge=1)]
    surface: Literal["document_content", "tool_response"]
    payload: Text


Injection = Annotated[FaultInjection | AttackInjection, Field(discriminator="kind")]
Pointer = Annotated[str, Field(pattern=r"^(?:/(?:[^~/]|~[01])*)+$")]


class StateEquals(Contract):
    source: Literal["final_state"]
    op: Literal["equals"]
    pointer: Pointer
    expected: JsonValue


class StateAbsent(Contract):
    source: Literal["final_state"]
    op: Literal["absent"]
    pointer: Pointer


class TraceCheck(Contract):
    source: Literal["trace"]
    op: Literal["count"]
    tool: ToolName
    decision: Literal["allowed", "denied", "any"]
    executed: bool | None = None
    minimum: Annotated[int, Field(ge=0)] = 0
    maximum: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("maximum must be at least minimum")
        if self.decision == "denied" and self.executed is True:
            raise ValueError("denied operations cannot be executed")
        return self


class ResponseCheck(Contract):
    source: Literal["response"]
    op: Literal["contains", "not_contains"]
    text: Text


Check = StateEquals | StateAbsent | TraceCheck | ResponseCheck


class SuccessPath(Contract):
    """All checks must pass; any complete path may satisfy task success."""

    path_id: Identifier
    checks: list[Check] = Field(min_length=1)


class StateChange(Contract):
    entity: Literal["documents", "customers", "orders", "payments", "accounts", "tasks"]
    record_id: Identifier | Literal["*"]
    operation: Literal["create", "update", "delete"]
    fields: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        if len(self.fields) != len(set(self.fields)):
            raise ValueError("state-change fields must be unique")
        return self


class ExpectedOutcome(Contract):
    final_state: list[StateEquals | StateAbsent] = Field(min_length=1)
    allowed_changes: list[StateChange]
    forbidden_changes: list[StateChange]
    success_paths: list[SuccessPath] = Field(min_length=1)
    # All unlisted changes are forbidden; forbidden rules override allowed rules.
    unlisted_changes: Literal["forbid"] = "forbid"


class ExecutionBudget(Contract):
    max_model_calls: Annotated[int, Field(ge=1, le=100)] = 10
    max_tool_calls: Annotated[int, Field(ge=1, le=100)] = 20
    max_wall_seconds: Annotated[int, Field(ge=1, le=3600)] = 120
    max_total_tokens: Annotated[int, Field(ge=1)] = 16000
    max_cost_usd: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 1.0


class Metadata(Contract):
    split: Literal["development", "held_out"]
    author: Text
    description: Text
    tags: list[Identifier] = Field(default_factory=list)


class Scenario(Contract):
    schema_version: Literal["1.0"]
    scenario_id: Identifier
    scenario_version: Annotated[int, Field(ge=1)]
    category: Category
    user_request: Text
    fixture: EnvironmentFixture
    actor: Actor
    tools: ToolAccess
    injections: list[Injection] = Field(default_factory=list)
    expected: ExpectedOutcome
    attacker_objective: list[Check] | None = Field(default=None, min_length=1)
    budget: ExecutionBudget = Field(default_factory=ExecutionBudget)
    metadata: Metadata

    @model_validator(mode="after")
    def validate_scenario(self) -> Self:
        for injection in self.injections:
            if injection.tool not in self.tools.available:
                raise ValueError("injection tool must be available")
            if injection.on_call > self.budget.max_tool_calls:
                raise ValueError("injection trigger exceeds tool-call budget")
            if (
                isinstance(injection, AttackInjection)
                and injection.surface == "document_content"
                and injection.tool not in {"search_documents", "get_document"}
            ):
                raise ValueError("document_content attacks require a document tool")
        triggers = [(item.tool, item.on_call) for item in self.injections]
        if len(triggers) != len(set(triggers)):
            raise ValueError("injection triggers must be unique")
        if self.category == "tool_failure" and not any(
            isinstance(item, FaultInjection) for item in self.injections
        ):
            raise ValueError("tool_failure scenarios require a fault injection")
        if self.category == "prompt_injection" and (
            not any(isinstance(item, AttackInjection) for item in self.injections)
            or self.attacker_objective is None
        ):
            raise ValueError("prompt_injection requires an attack and attacker objective")
        paths = self.expected.success_paths
        if len({path.path_id for path in paths}) != len(paths):
            raise ValueError("success path IDs must be unique")
        checks = [check for path in paths for check in path.checks]
        checks.extend(self.attacker_objective or [])
        if any(
            isinstance(check, TraceCheck) and check.tool not in self.tools.available
            for check in checks
        ):
            raise ValueError("trace checks must reference available tools")
        return self
