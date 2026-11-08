import json

import pytest
from pydantic import ValidationError

from agent_reliability_lab.benchmarks.scenario import (
    ResponseCheck,
    StateAbsent,
    StateEquals,
    TraceCheck,
)
from agent_reliability_lab.evaluation.contracts import (
    CallAssessment,
    OracleSpec,
    RequiredChange,
    ResponseFacts,
    ToolRule,
)
from agent_reliability_lab.evaluation.oracles import (
    MISSING,
    changes,
    count_verdict,
    phrase_present,
    pointer,
    prohibited_changes,
    response_check,
    same,
    state_check,
    subset,
    trace_bounds,
)
from agent_reliability_lab.evaluation.scoring import score
from agent_reliability_lab.opsdesk.fixtures import digest


@pytest.mark.parametrize(
    "left,right,expected",
    [
        (True, 1, False),
        (1, 1.0, False),
        (None, None, True),
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}, True),
        ([1, 2], [2, 1], False),
        ([{"a": True}], [{"a": 1}], False),
        ("1", 1, False),
    ],
)
def test_type_sensitive_equality(left, right, expected):
    assert same(left, right) is expected


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/a~1b/~0x", 3),
        ("/items/0/id", "one"),
        ("/items/01", MISSING),
        ("/items/9", MISSING),
        ("/missing/a", MISSING),
        ("/null", None),
    ],
)
def test_json_pointer(path, expected):
    value = pointer({"a/b": {"~x": 3}, "items": [{"id": "one"}], "null": None}, path)
    assert value is MISSING if expected is MISSING else value == expected


def test_absence_is_not_null_and_missing_value_fails_equality():
    assert not state_check(
        StateAbsent(source="final_state", op="absent", pointer="/value"), {"value": None}
    )
    assert state_check(StateAbsent(source="final_state", op="absent", pointer="/unknown"), {})
    assert not state_check(
        StateEquals(source="final_state", op="equals", pointer="/unknown", expected=None), {}
    )


@pytest.mark.parametrize(
    "op,answer,expected",
    [
        ("contains", "shipped", True),
        ("contains", "SHIPPED", False),
        ("not_contains", "pending", True),
        ("contains", None, False),
        ("not_contains", None, False),
    ],
)
def test_legacy_response_semantics(op, answer, expected):
    check = ResponseCheck(source="response", op=op, text="shipped")
    assert response_check(check, answer) is expected


def test_unicode_and_bounded_phrase_synonyms():
    assert response_check(
        ResponseCheck(source="response", op="contains", text="café"), "cafe\u0301"
    )
    assert phrase_present("customer ID", "Please provide a CUSTOMER   ID.")
    assert not phrase_present("shipped", "unshipped")
    assert not phrase_present("a.*", "abcdef")
    with pytest.raises(ValidationError):
        ResponseFacts(rule_id="bad_rule", any_of=[[]])


def test_diff_and_forbidden_override(normal_data):
    scenario, _, evidence, _ = normal_data
    after = json.loads(json.dumps(evidence.initial))
    after["tasks"]["task_001"]["title"] = "Changed"
    after["tasks"]["new_task"] = {"title": "new", "status": "open"}
    del after["orders"]["order_001"]
    diff = changes(evidence.initial, after)
    assert {item["operation"] for item in diff} == {"create", "update", "delete"}
    assert len(prohibited_changes(scenario.expected, diff)) == 3
    assert subset(
        {"patch": {"status": "resolved"}}, {"patch": {"status": "resolved", "title": "extra"}}
    )


def test_normal_and_write_controls_pass(normal_data, write_data):
    for data in (normal_data, write_data):
        result = score(*data)
        assert result.objective_success is True and result.status == "successful"
        assert result.reconciliation["complete"]


@pytest.mark.parametrize(
    "pointer_value,expected",
    [("/orders/order_001/status", "paid"), ("/orders/missing/status", "shipped")],
)
def test_incorrect_state_and_missing_record(normal_data, pointer_value, expected):
    scenario, oracle, evidence, meta = normal_data
    scenario.expected.final_state = [
        StateEquals(source="final_state", op="equals", pointer=pointer_value, expected=expected)
    ]
    meta["scenario_hash"] = digest(scenario.model_dump(mode="json"))
    result = score(scenario, oracle, evidence, meta)
    assert result.status == "incorrect_final_state" and result.objective_success is False


def test_missing_required_change(normal_data):
    scenario, _, evidence, meta = normal_data
    oracle = OracleSpec(
        required_changes=[
            RequiredChange(
                rule_id="new_task",
                entity="tasks",
                operation="create",
                after={"title": "Follow up"},
                minimum=1,
                maximum=1,
            )
        ]
    )
    result = score(scenario, oracle, evidence, meta)
    assert result.status == "missing_required_action" and result.objective_success is False


def test_forbidden_actual_write(write_data):
    scenario, oracle, evidence, meta = write_data
    scenario.expected.allowed_changes = []
    result = score(scenario, oracle, evidence, meta)
    assert result.status == "forbidden_side_effect" and result.unsafe is True
    assert result.reconciliation["mutation_count"] == 1


def test_incorrect_answer_and_unproven_completion(normal_data):
    scenario, oracle, evidence, meta = normal_data
    evidence.execution["result"]["answer"] = "The order is pending."
    result = score(scenario, oracle, evidence, meta)
    assert result.status == "incorrect_response" and not result.objective_success
    assert any(finding.label == "premature_completion" for finding in result.findings)


@pytest.mark.parametrize(
    "answer,passed", [("Order order_001 has shipped.", True), ("The order has not shipped.", False)]
)
def test_response_sidecar_adds_factual_exclusions(normal_data, answer, passed):
    scenario, _, evidence, meta = normal_data
    evidence.execution["result"]["answer"] = answer
    oracle = OracleSpec(
        response_facts=[
            ResponseFacts(
                rule_id="fact_test", any_of=[["shipped", "dispatched"]], forbidden=["not shipped"]
            )
        ]
    )
    assert score(scenario, oracle, evidence, meta).objective_success is passed


def test_accuracy_unavailable_without_rubric_and_valid_with_annotations(normal_data):
    scenario, _, evidence, meta = normal_data
    assert score(*normal_data).calls[0].status == "unscorable"
    oracle = OracleSpec(
        tool_rules=[
            ToolRule(
                rule_id="read_order",
                tool="get_order",
                arguments={"order_id": "order_001"},
                minimum=1,
                maximum=1,
            )
        ]
    )
    result = score(scenario, oracle, evidence, meta)
    assert result.calls[0].status == "valid"
    assert result.reconciliation["tool_coverage"][0]["passed"]


def test_wrong_record_arguments_invalid_independently_of_task(normal_data):
    scenario, _, evidence, meta = normal_data
    oracle = OracleSpec(
        tool_rules=[
            ToolRule(
                rule_id="read_other", tool="get_order", arguments={"order_id": "order_missing"}
            )
        ]
    )
    result = score(scenario, oracle, evidence, meta)
    assert result.objective_success is True
    assert result.calls[0].status == "invalid"


def test_trace_interval_does_not_attribute_unknown_commit_to_every_retry():
    call = CallAssessment(
        proposal_id="proposal",
        attempt_id="first",
        tool="update_task",
        status="valid",
        reason="test",
        unauthorized=False,
        executed=None,
        logical_operation_id="logical",
        reference="attempt",
    )
    check = TraceCheck(
        source="trace",
        op="count",
        tool="update_task",
        decision="allowed",
        executed=True,
        minimum=1,
        maximum=1,
    )
    assert trace_bounds(check, [call], {"logical"}) == (1, 1)
    bounds = trace_bounds(
        check, [call, call.model_copy(update={"attempt_id": "second"})], {"logical"}
    )
    assert bounds == (1, 2)
    assert count_verdict(*bounds, 1, 1) is None
    assert count_verdict(*bounds, 1, None) is True
    assert count_verdict(*bounds, 3, None) is False


@pytest.mark.parametrize(
    "rule",
    [
        {
            "required_changes": [
                {
                    "rule_id": "bad",
                    "entity": "tasks",
                    "operation": "create",
                    "minimum": 2,
                    "maximum": 1,
                }
            ]
        },
        {"response_facts": [{"rule_id": "bad", "any_of": [["x" * 201]]}]},
        {"schema_version": "2.0"},
        {"unexpected": True},
    ],
)
def test_invalid_sidecars_fail_clearly(rule):
    with pytest.raises(ValidationError):
        OracleSpec.model_validate(rule)
