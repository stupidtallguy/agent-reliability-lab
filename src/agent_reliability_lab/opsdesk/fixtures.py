"""Versioned seed bundles enrich legacy scenarios without changing their contracts."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Self

import sqlalchemy as sa
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy.engine import Connection

from agent_reliability_lab.benchmarks.scenario import (
    Actor,
    Contract,
    EnvironmentFixture,
    Identifier,
    Scenario,
    ToolAccess,
)
from agent_reliability_lab.opsdesk import tables as t

SEED_TIME = datetime(2026, 1, 15, 12, tzinfo=UTC)
MUTATION_EPOCH = datetime(2026, 2, 1, tzinfo=UTC)


class CustomerDetails(Contract):
    email: Annotated[str, Field(pattern=r"^[a-z0-9_.-]+@customers\.opsdesk\.invalid$")]


class OrderDetails(Contract):
    total_amount: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "USD"
    created_at: AwareDatetime = SEED_TIME


class TaskDetails(Contract):
    description: Annotated[str, Field(max_length=10000)] = "Synthetic support task."
    priority: Annotated[str, Field(pattern=r"^(low|normal|high)$")] = "normal"
    assigned_actor_id: Identifier | None = None
    order_id: Identifier | None = None


class DocumentDetails(Contract):
    category: Identifier = "policy"
    version: Annotated[int, Field(ge=1)] = 1


class SeedSpec(Contract):
    """Fixture wrapper v1; legacy EnvironmentFixture remains unchanged."""

    seed_format: str = "1.0"
    environment: EnvironmentFixture
    actors: list[Actor] = Field(min_length=1)
    customer_details: dict[str, CustomerDetails] = Field(default_factory=dict)
    order_details: dict[str, OrderDetails] = Field(default_factory=dict)
    task_details: dict[str, TaskDetails] = Field(default_factory=dict)
    document_details: dict[str, DocumentDetails] = Field(default_factory=dict)

    @model_validator(mode="after")
    def references(self) -> Self:
        if self.seed_format != "1.0":
            raise ValueError("unsupported seed_format")
        actors = {item.actor_id: item for item in self.actors}
        if len(actors) != len(self.actors):
            raise ValueError("duplicate fixture actor_id")
        env = self.environment
        if any(detail.created_at >= MUTATION_EPOCH for detail in self.order_details.values()):
            raise ValueError("seed orders must precede the fixed simulation mutation epoch")
        for details, records, identifier in [
            (self.customer_details, env.customers, "customer_id"),
            (self.order_details, env.orders, "order_id"),
            (self.task_details, env.tasks, "task_id"),
            (self.document_details, env.documents, "document_id"),
        ]:
            if not details.keys() <= {getattr(item, identifier) for item in records}:
                raise ValueError("details must reference existing fixture records")
        orders = {item.order_id: item for item in env.orders}
        for task in env.tasks:
            detail = self.task_details.get(task.task_id, TaskDetails())
            if detail.assigned_actor_id is not None:
                actor = actors.get(detail.assigned_actor_id)
                if actor is None or actor.tenant_id != task.tenant_id:
                    raise ValueError("task assignee must exist in the same tenant")
            if detail.order_id is not None:
                order = orders.get(detail.order_id)
                if (
                    order is None
                    or order.tenant_id != task.tenant_id
                    or order.customer_id != task.customer_id
                ):
                    raise ValueError("task order must belong to its customer and tenant")
        return self


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate_json(path.read_text(encoding="utf-8"))


def from_scenario(scenario: Scenario) -> SeedSpec:
    return SeedSpec(environment=scenario.fixture, actors=[scenario.actor])


def load_baseline() -> SeedSpec:
    return SeedSpec.model_validate_json(
        Path(__file__).with_name("data").joinpath("baseline.json").read_text(encoding="utf-8")
    )


def baseline_access() -> ToolAccess:
    return ToolAccess(
        available=[
            "search_documents",
            "get_document",
            "get_order",
            "get_customer",
            "list_customer_orders",
            "list_tasks",
            "create_task",
            "update_task",
        ],
        permitted=[
            "search_documents",
            "get_document",
            "get_order",
            "get_customer",
            "list_customer_orders",
            "list_tasks",
            "create_task",
            "update_task",
        ],
    )


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def populate(connection: Connection, seed: SeedSpec) -> None:
    """Caller owns the transaction. Constraints validate the entire insert atomically."""
    env = seed.environment
    records = [
        *seed.actors,
        *env.customers,
        *env.documents,
        *env.orders,
        *env.payments,
        *env.accounts,
        *env.tasks,
    ]
    for tenant in sorted({item.tenant_id for item in records}):
        connection.execute(t.tenants.insert().values(tenant_id=tenant))
    for actor in seed.actors:
        connection.execute(t.actors.insert().values(**actor.model_dump()))
    for customer in env.customers:
        detail = seed.customer_details.get(customer.customer_id)
        connection.execute(
            t.customers.insert().values(
                **customer.model_dump(),
                email=detail.email
                if detail
                else f"{customer.customer_id}@customers.opsdesk.invalid",
                version=1,
                created_at=datetime(2025, 1, 1, tzinfo=UTC),
            )
        )
    for order in env.orders:
        detail = seed.order_details.get(order.order_id)
        amount = sum(
            (Decimal(p.amount_cents) / 100 for p in env.payments if p.order_id == order.order_id),
            Decimal(0),
        )
        created = detail.created_at if detail else SEED_TIME
        connection.execute(
            t.orders.insert().values(
                **order.model_dump(),
                total_amount=detail.total_amount if detail else amount,
                currency=detail.currency if detail else "USD",
                version=1,
                created_at=created,
                updated_at=created,
            )
        )
    for payment in env.payments:
        data = payment.model_dump(exclude={"amount_cents"})
        detail = seed.order_details.get(payment.order_id)
        paid_at = max(SEED_TIME, detail.created_at) if detail else SEED_TIME
        connection.execute(
            t.payments.insert().values(
                **data,
                amount=Decimal(payment.amount_cents) / 100,
                paid_at=paid_at if payment.status == "settled" else None,
            )
        )
    for account in env.accounts:
        connection.execute(t.accounts.insert().values(**account.model_dump()))
    for task in env.tasks:
        detail = seed.task_details.get(task.task_id, TaskDetails())
        order_detail = seed.order_details.get(detail.order_id)
        created = max(SEED_TIME, order_detail.created_at) if order_detail else SEED_TIME
        connection.execute(
            t.tasks.insert().values(
                **task.model_dump(),
                **detail.model_dump(),
                created_at=created,
                updated_at=created,
            )
        )
    for document in env.documents:
        detail = seed.document_details.get(document.document_id, DocumentDetails())
        connection.execute(
            t.documents.insert().values(
                **document.model_dump(),
                **detail.model_dump(),
                published_at=SEED_TIME,
                trust_classification="untrusted",
            )
        )


def logical_state(connection: Connection) -> dict:
    """Canonical JSON: exact decimals, UTC times, stable IDs, no physical metadata."""
    state = {}
    for table in t.DOMAIN_TABLES:
        identifier = list(table.primary_key.columns)[0].name
        columns = [column for column in table.c if column.name != "search_vector"]
        rows = connection.execute(sa.select(*columns).order_by(table.c[identifier])).mappings()
        records = {}
        for row in rows:
            data = dict(row)
            for key, value in data.items():
                if isinstance(value, Decimal):
                    data[key] = format(value, ".2f")
                elif isinstance(value, datetime):
                    data[key] = value.astimezone(UTC).isoformat()
            records[data[identifier]] = data
        state[table.name] = records
    return state


def benchmark_state(connection: Connection) -> dict:
    """Legacy v1 projection keeps infrastructure timestamps out of domain diffs."""
    state = logical_state(connection)
    fields = {
        "documents": ("document_id", "tenant_id", "title", "content"),
        "customers": ("customer_id", "tenant_id", "display_name"),
        "orders": ("order_id", "customer_id", "tenant_id", "status"),
        "payments": ("payment_id", "order_id", "tenant_id", "status"),
        "accounts": ("account_id", "customer_id", "tenant_id", "status"),
        "tasks": ("task_id", "tenant_id", "customer_id", "title", "status", "version"),
    }
    result = {
        name: {key: {field: row[field] for field in names} for key, row in state[name].items()}
        for name, names in fields.items()
    }
    for key, row in state["payments"].items():
        result["payments"][key]["amount_cents"] = int(Decimal(row["amount"]) * 100)
    return result
