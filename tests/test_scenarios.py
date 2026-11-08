"""Validate the specification boundary, not an unimplemented evaluation runtime."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_reliability_lab.benchmarks import Scenario

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "benchmarks" / "development").glob("*.json"))


@pytest.fixture
def specification() -> dict:
    return json.loads((ROOT / "benchmarks/development/normal_order_status.json").read_text())


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.stem)
def test_examples_validate_and_round_trip(path: Path) -> None:
    scenario = Scenario.model_validate_json(path.read_text(encoding="utf-8"))
    assert scenario.metadata.split == "development"
    assert Scenario.model_validate_json(scenario.model_dump_json()) == scenario


def test_examples_cover_six_categories() -> None:
    assert len(EXAMPLES) == 6
    scenarios = [Scenario.model_validate_json(path.read_text()) for path in EXAMPLES]
    assert len({item.scenario_id for item in scenarios}) == 6
    assert {item.category for item in scenarios} == {
        "normal",
        "multi_step",
        "tool_failure",
        "prompt_injection",
        "authorization",
        "ambiguous",
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "2.0", "schema_version"),
        ("scenario_id", "../escape", "scenario_id"),
        ("scenario_version", "1", "valid integer"),
        ("user_request", "   ", "at least 1 character"),
        ("category", "invented", "category"),
        ("unexpected", True, "Extra inputs"),
    ],
)
def test_invalid_top_level_fields(specification: dict, field: str, value, message: str) -> None:
    specification[field] = value
    with pytest.raises(ValidationError, match=message):
        Scenario.model_validate(specification)


def test_missing_required_field(specification: dict) -> None:
    del specification["expected"]
    with pytest.raises(ValidationError, match="Field required"):
        Scenario.model_validate(specification)


@pytest.mark.parametrize(
    ("tools", "message"),
    [
        ({"available": ["arbitrary_sql"], "permitted": []}, "Input should be"),
        ({"available": ["get_order"], "permitted": ["update_task"]}, "must be available"),
        ({"available": ["get_order", "get_order"], "permitted": []}, "duplicates"),
        (
            {"available": ["get_order"], "permitted": [], "approval_required": ["get_order"]},
            "must be permitted",
        ),
        (
            {
                "available": ["get_order"],
                "permitted": ["get_order"],
                "approval_required": ["get_order"],
            },
            "only for task writes",
        ),
    ],
)
def test_invalid_permissions(specification: dict, tools: dict, message: str) -> None:
    specification["tools"] = tools
    with pytest.raises(ValidationError, match=message):
        Scenario.model_validate(specification)


def test_availability_does_not_imply_permission(specification: dict) -> None:
    specification["tools"]["available"].append("update_task")
    scenario = Scenario.model_validate(specification)
    assert "update_task" not in scenario.tools.permitted


@pytest.mark.parametrize("collection,key", [("customers", "customer_id"), ("orders", "order_id")])
def test_duplicate_fixture_ids(specification: dict, collection: str, key: str) -> None:
    records = specification["fixture"][collection]
    records.append(copy.deepcopy(records[0]))
    with pytest.raises(ValidationError, match=f"duplicate {key}"):
        Scenario.model_validate(specification)


@pytest.mark.parametrize("collection", ["orders", "accounts", "tasks"])
def test_missing_customer_reference(specification: dict, collection: str) -> None:
    specification["fixture"][collection][0]["customer_id"] = "missing_customer"
    with pytest.raises(ValidationError, match="customer reference"):
        Scenario.model_validate(specification)


def test_cross_tenant_reference(specification: dict) -> None:
    specification["fixture"]["orders"][0]["tenant_id"] = "another_tenant"
    with pytest.raises(ValidationError, match="same tenant"):
        Scenario.model_validate(specification)


def test_payment_reference(specification: dict) -> None:
    specification["fixture"]["payments"][0]["order_id"] = "missing_order"
    with pytest.raises(ValidationError, match="payment order reference"):
        Scenario.model_validate(specification)


@pytest.mark.parametrize(
    "category,message",
    [
        ("tool_failure", "require a fault"),
        ("prompt_injection", "requires an attack"),
    ],
)
def test_category_requires_injection(specification: dict, category: str, message: str) -> None:
    specification["category"] = category
    with pytest.raises(ValidationError, match=message):
        Scenario.model_validate(specification)


@pytest.mark.parametrize(
    "tool,on_call,message",
    [
        ("get_order", 0, "greater than or equal to 1"),
        ("get_order", 21, "exceeds tool-call budget"),
        ("get_document", 1, "must be available"),
    ],
)
def test_invalid_injection_trigger(
    specification: dict, tool: str, on_call: int, message: str
) -> None:
    specification["injections"] = [
        {"kind": "fault", "tool": tool, "on_call": on_call, "fault": "timeout", "recoverable": True}
    ]
    with pytest.raises(ValidationError, match=message):
        Scenario.model_validate(specification)


def test_duplicate_injection_trigger(specification: dict) -> None:
    fault = {
        "kind": "fault",
        "tool": "get_order",
        "on_call": 1,
        "fault": "timeout",
        "recoverable": True,
    }
    specification["injections"] = [fault, copy.deepcopy(fault)]
    with pytest.raises(ValidationError, match="triggers must be unique"):
        Scenario.model_validate(specification)


def test_document_attack_requires_document_tool(specification: dict) -> None:
    specification["injections"] = [
        {
            "kind": "attack",
            "tool": "get_order",
            "on_call": 1,
            "surface": "document_content",
            "payload": "inert attack",
        }
    ]
    with pytest.raises(ValidationError, match="require a document tool"):
        Scenario.model_validate(specification)


def test_attack_requires_objective() -> None:
    payload = json.loads((ROOT / "benchmarks/development/injection_policy_canary.json").read_text())
    payload["attacker_objective"] = None
    with pytest.raises(ValidationError, match="attacker objective"):
        Scenario.model_validate(payload)


@pytest.mark.parametrize("pointer", ["orders/order_001", "/orders/~2bad"])
def test_invalid_state_pointer(specification: dict, pointer: str) -> None:
    specification["expected"]["final_state"][0]["pointer"] = pointer
    with pytest.raises(ValidationError, match="pointer"):
        Scenario.model_validate(specification)


def test_null_and_absent_are_distinct_contracts(specification: dict) -> None:
    specification["expected"]["final_state"] = [
        {"source": "final_state", "op": "equals", "pointer": "/nullable", "expected": None},
        {"source": "final_state", "op": "absent", "pointer": "/missing"},
    ]
    assert len(Scenario.model_validate(specification).expected.final_state) == 2


@pytest.mark.parametrize(
    "change,message",
    [
        ({"minimum": 2, "maximum": 1}, "maximum must"),
        ({"decision": "denied", "executed": True}, "cannot be executed"),
        ({"tool": "get_document"}, "reference available tools"),
    ],
)
def test_invalid_trace_checks(specification: dict, change: dict, message: str) -> None:
    specification["expected"]["success_paths"][0]["checks"][1].update(change)
    with pytest.raises(ValidationError, match=message):
        Scenario.model_validate(specification)


def test_duplicate_success_path(specification: dict) -> None:
    paths = specification["expected"]["success_paths"]
    paths.append(copy.deepcopy(paths[0]))
    with pytest.raises(ValidationError, match="path IDs must be unique"):
        Scenario.model_validate(specification)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_tool_calls", 0),
        ("max_cost_usd", float("nan")),
        ("max_wall_seconds", "120"),
    ],
)
def test_invalid_budget(specification: dict, field: str, value) -> None:
    specification["budget"][field] = value
    with pytest.raises(ValidationError, match=field):
        Scenario.model_validate(specification)


def test_schema_is_exportable() -> None:
    schema = Scenario.model_json_schema()
    assert schema["additionalProperties"] is False
    assert "expected" in schema["required"]
    assert "$defs" in schema


def test_defaults_do_not_share_lists(specification: dict) -> None:
    first = Scenario.model_validate(specification)
    second = Scenario.model_validate(specification)
    first.metadata.tags.append("local_mutation")
    assert "local_mutation" not in second.metadata.tags


@pytest.mark.parametrize("field", ["final_state", "success_paths"])
def test_outcomes_require_evidence(specification: dict, field: str) -> None:
    specification["expected"][field] = []
    with pytest.raises(ValidationError, match=field):
        Scenario.model_validate(specification)


def test_empty_success_path_fails(specification: dict) -> None:
    specification["expected"]["success_paths"][0]["checks"] = []
    with pytest.raises(ValidationError, match="checks"):
        Scenario.model_validate(specification)


def test_duplicate_mutation_fields_fail(specification: dict) -> None:
    specification["expected"]["allowed_changes"] = [
        {
            "entity": "tasks",
            "record_id": "task_001",
            "operation": "update",
            "fields": ["status", "status"],
        }
    ]
    with pytest.raises(ValidationError, match="fields must be unique"):
        Scenario.model_validate(specification)


def test_unknown_role_fails(specification: dict) -> None:
    specification["actor"]["role"] = "administrator"
    with pytest.raises(ValidationError, match="role"):
        Scenario.model_validate(specification)


def test_invalid_injection_discriminator(specification: dict) -> None:
    specification["injections"] = [{"kind": "execute_code", "payload": "inert"}]
    with pytest.raises(ValidationError, match="kind"):
        Scenario.model_validate(specification)
