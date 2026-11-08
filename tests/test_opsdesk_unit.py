"""Fast specification and safety checks with no database or Docker dependency."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_reliability_lab.opsdesk.contracts import (
    ActorContext,
    DocumentSearch,
    TaskCreate,
    TaskPatch,
    TaskUpdate,
)
from agent_reliability_lab.opsdesk.database import make_engine, schema_for
from agent_reliability_lab.opsdesk.fixtures import (
    SeedSpec,
    digest,
    from_scenario,
    load_baseline,
    load_scenario,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "value", ["public", "pg_catalog", "x", "A_run", "../run", "a;drop", "a" * 33]
)
def test_invalid_run_identifiers(value: str) -> None:
    # Even reserved identifiers with valid syntax become a safe prefixed schema.
    if value in {"public", "pg_catalog"}:
        assert schema_for(value).startswith("opsdesk_run_")
    else:
        with pytest.raises(ValueError, match="run_id"):
            schema_for(value)


@pytest.mark.parametrize(
    "url",
    [
        "sqlite://",
        "postgresql+psycopg://localhost/production",
        "postgresql://localhost/opsdesk_lab",
        "postgresql+psycopg://localhost/postgres",
    ],
)
def test_non_sandbox_urls_rejected_before_connecting(url: str) -> None:
    with pytest.raises(ValueError, match="dedicated"):
        make_engine(url, allow_sandbox=True)


def test_explicit_opt_in_is_required() -> None:
    with pytest.raises(ValueError, match="ALLOW_SANDBOX"):
        make_engine("postgresql+psycopg://localhost/opsdesk_lab")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": None},
        {"title": ""},
        {"status": "closed"},
        {"role": "supervisor"},
    ],
)
def test_invalid_task_patches(payload: dict) -> None:
    with pytest.raises(ValidationError):
        TaskPatch.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"customer_id": "customer_001", "title": "Task", "idempotency_key": ""},
        {"customer_id": "customer_001", "title": " ", "idempotency_key": "key"},
        {"customer_id": "../escape", "title": "Task", "idempotency_key": "key"},
    ],
)
def test_invalid_task_creation(payload: dict) -> None:
    with pytest.raises(ValidationError):
        TaskCreate.model_validate(payload)


def test_context_cannot_claim_a_role() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        ActorContext.model_validate(
            {"actor_id": "viewer_001", "tenant_id": "opsdesk", "role": "supervisor"}
        )


def test_version_and_search_bounds() -> None:
    with pytest.raises(ValidationError):
        TaskUpdate(
            task_id="task_001",
            expected_version=0,
            patch=TaskPatch(status="resolved"),
            idempotency_key="key",
        )
    with pytest.raises(ValidationError):
        DocumentSearch(query="refund", limit=21)


def test_baseline_is_deterministic_and_entirely_synthetic() -> None:
    first, second = load_baseline(), load_baseline()
    assert first == second
    assert len(first.environment.customers) == 5
    assert len(first.environment.orders) == 6
    assert len(first.environment.documents) == 4
    assert {item.role for item in first.actors} == {"viewer", "support_agent", "supervisor"}
    assert all(detail.email.endswith(".invalid") for detail in first.customer_details.values())
    assert digest(first.model_dump(mode="json")) == digest(second.model_dump(mode="json"))


@pytest.mark.parametrize(
    "name", ["customer_details", "order_details", "task_details", "document_details"]
)
def test_enrichment_must_reference_existing_records(name: str) -> None:
    payload = load_baseline().model_dump(mode="json")
    payload[name]["missing_record"] = copy.deepcopy(next(iter(payload[name].values())))
    with pytest.raises(ValidationError, match="existing fixture records"):
        SeedSpec.model_validate_json(json.dumps(payload))


def test_assignee_and_order_integrity() -> None:
    seed = load_baseline()
    seed.task_details["task_001"].assigned_actor_id = "viewer_other"
    with pytest.raises(ValidationError, match="same tenant"):
        SeedSpec.model_validate_json(seed.model_dump_json())
    seed = load_baseline()
    seed.task_details["task_001"].order_id = "order_003"
    with pytest.raises(ValidationError, match="customer and tenant"):
        SeedSpec.model_validate_json(seed.model_dump_json())


@pytest.mark.parametrize("path", sorted((ROOT / "benchmarks/development").glob("*.json")))
def test_legacy_scenario_seed_adapter(path: Path) -> None:
    scenario = load_scenario(path)
    seed = from_scenario(scenario)
    assert seed.environment == scenario.fixture
    assert seed.actors == [scenario.actor]


def test_seed_format_is_versioned() -> None:
    payload = load_baseline().model_dump(mode="json")
    payload["seed_format"] = "2.0"
    with pytest.raises(ValidationError, match="seed_format"):
        SeedSpec.model_validate_json(json.dumps(payload))
