"""Wire contracts derive constraints from the existing business DTOs."""

from copy import deepcopy
from typing import Generic, Literal, Self, TypeVar

from pydantic import BaseModel, create_model, model_validator

from agent_reliability_lab.benchmarks.scenario import Contract, Identifier
from agent_reliability_lab.opsdesk.contracts import TaskCreate, TaskUpdate

Domain = Literal["documents", "business", "tasks"]


class DocumentLookup(Contract):
    document_id: Identifier


class OrderLookup(Contract):
    order_id: Identifier


class CustomerLookup(Contract):
    customer_id: Identifier


def model_without_key(name: str, original: type[BaseModel]) -> type[BaseModel]:
    return create_model(
        name,
        __base__=Contract,
        **{
            field_name: (field.annotation, deepcopy(field))
            for field_name, field in original.model_fields.items()
            if field_name != "idempotency_key"
        },
    )


CreateTaskInput = model_without_key("CreateTaskInput", TaskCreate)
UpdateTaskInput = model_without_key("UpdateTaskInput", TaskUpdate)


class SafeError(Contract):
    code: str
    message: str
    retryable: bool = False
    correlation_id: str


class Provenance(Contract):
    source: Literal["opsdesk"] = "opsdesk"
    domain: Domain
    tool: str
    fixture_id: str
    fixture_version: str
    seed_hash: str
    trust_classification: Literal["untrusted"] = "untrusted"


Data = TypeVar("Data")


class Envelope(Contract, Generic[Data]):
    contract_version: Literal["1.0"] = "1.0"
    data: Data | None
    error: SafeError | None
    provenance: Provenance

    @model_validator(mode="after")
    def exactly_one_outcome(self) -> Self:
        if (self.data is None) == (self.error is None):
            raise ValueError("exactly one of data and error must be present")
        return self
