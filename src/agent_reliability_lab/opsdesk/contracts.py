"""Typed internal service boundary, separate from future MCP serialization."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, Self, TypeVar

from pydantic import Field, model_validator

from agent_reliability_lab.benchmarks.scenario import Contract, Identifier

TaskStatus = Literal["open", "in_progress", "resolved"]


class ActorContext(Contract):
    """Trusted host identity. Role is always loaded from the sandbox database."""

    actor_id: Identifier
    tenant_id: Identifier


class Lookup(Contract):
    record_id: Identifier


class PageInput(Contract):
    limit: Annotated[int, Field(ge=1, le=50)] = 20
    after_id: Identifier | None = None


class CustomerOrders(PageInput):
    customer_id: Identifier


class TaskList(PageInput):
    customer_id: Identifier | None = None
    status: TaskStatus | None = None


class DocumentSearch(PageInput):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    limit: Annotated[int, Field(ge=1, le=20)] = 5


class TaskCreate(Contract):
    customer_id: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128)]


class TaskPatch(Contract):
    title: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    status: TaskStatus | None = None

    @model_validator(mode="after")
    def nonempty_patch(self) -> Self:
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set
        ):
            raise ValueError("patch must contain at least one non-null field")
        return self


class TaskUpdate(Contract):
    task_id: Identifier
    expected_version: Annotated[int, Field(ge=1)]
    patch: TaskPatch
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128)]


class CustomerView(Contract):
    customer_id: str
    display_name: str
    email: str
    version: int
    created_at: datetime


class OrderView(Contract):
    order_id: str
    customer_id: str
    status: str
    total_amount: Decimal
    currency: str
    version: int
    created_at: datetime
    updated_at: datetime


class DocumentView(Contract):
    document_id: str
    title: str
    content: str
    category: str
    version: int
    published_at: datetime
    trust_classification: Literal["untrusted"]


class DocumentHit(Contract):
    document_id: str
    title: str
    snippet: str
    version: int
    trust_classification: Literal["untrusted"] = "untrusted"


class TaskView(Contract):
    task_id: str
    customer_id: str
    title: str
    description: str
    status: TaskStatus
    priority: str
    assigned_actor_id: str | None
    order_id: str | None
    version: int
    created_at: datetime
    updated_at: datetime


Item = TypeVar("Item")


class Page(Contract, Generic[Item]):
    items: list[Item]
    next_after_id: str | None


class ErrorDetail(Contract):
    code: str
    message: str
    retryable: bool = False


class ServiceError(Exception):
    """Safe domain error for a future adapter; never contains raw database diagnostics."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.detail = ErrorDetail(code=code, message=message, retryable=retryable)
        super().__init__(message)
