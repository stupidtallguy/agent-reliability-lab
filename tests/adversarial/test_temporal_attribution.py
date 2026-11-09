"""Decision boundaries use durable relationships, independently of PostgreSQL clocks."""

import copy
from types import SimpleNamespace

import pytest

from agent_reliability_lab.adversarial.attribution import (
    DecisionOrder,
    OrderingError,
    matches_effect,
    task_diff,
)
from agent_reliability_lab.evaluation.contracts import ExperimentConfig


def timeline(origin="pre", delayed_proposal=False):
    op = dict(
        proposal_id="write",
        operation_id="logical",
        tool="update_task",
        model_call_id="model_write",
        arguments_hash="args",
        turn=0,
        position=1,
    )
    call = {"name": "update_task", "call_id": "model_write"}
    requests = [
        dict(
            request_id="pre",
            turn=0,
            status="completed",
            calls=[{"name": "get_document", "call_id": "doc"}, call],
        ),
        dict(request_id="visible", turn=1, status="completed", calls=[call]),
        dict(request_id="later", turn=2, status="completed", calls=[call]),
    ]
    if origin != "pre":
        op.update(turn=1 if origin == "visible" else 2, position=0)

    def event(kind, **payload):
        return {
            "execution_id": "execution",
            "event_type": kind,
            "timestamp": "2000-01-01T00:00:00Z",
            "payload": {"correlation_id": "execution", **payload},
        }

    proposal = event(
        "tool_call_proposed",
        tool_call_id="write",
        logical_operation_id="logical",
        tool="update_task",
        arguments_hash="args",
    )
    events = [
        event("model_request", request_id="pre", input_hash="pre_input"),
        event("model_response", request_id="pre", call_count=2),
    ]
    if origin == "pre" and not delayed_proposal:
        events.append(proposal)
    events.extend(
        [
            event("tool_call_succeeded", attempt_id="doc_attempt", response_hash="response"),
            event("model_request", request_id="visible", input_hash="visible_input"),
            event(
                "injection_model_exposure",
                injection_id="attack",
                attempt_id="doc_attempt",
                request_id="visible",
                input_hash="visible_input",
                observed_response_hash="response",
            ),
            event("model_response", request_id="visible", call_count=1),
        ]
    )
    if origin != "later" and (origin != "pre" or delayed_proposal):
        events.append(proposal)
    events.extend(
        [
            event("model_request", request_id="later", input_hash="later_input"),
            event("model_response", request_id="later", call_count=1),
        ]
    )
    if origin == "later":
        events.append(proposal)
    events.append(
        event(
            "tool_call_started",
            attempt_id="write_attempt",
            tool_call_id="write",
            logical_operation_id="logical",
        )
    )
    for number, row in enumerate(events, 1):
        row["sequence"] = number
    evidence = SimpleNamespace(
        execution_id="execution",
        execution={"journal_seq": len(events)},
        events=events,
        requests=requests,
        attempts=[{"attempt_id": "write_attempt", "proposal_id": "write"}],
        audits=[{"sequence": 1}],
        receipts=[{"idempotency_key": "receipt"}],
    )
    return evidence, op


def carriers(evidence):
    return DecisionOrder(evidence).carriers(
        "attack", [{"injection_id": "attack", "attempt_id": "doc_attempt", "exposed": True}]
    )


@pytest.mark.parametrize("delayed", [False, True])
def test_pre_exposure_decision_never_becomes_eligible_by_dispatch_order(delayed):
    evidence, op = timeline(delayed_proposal=delayed)
    result = DecisionOrder(evidence).proposal(op, carriers(evidence))
    assert result["eligible"] is False
    assert result["reason"] == "pre_exposure_decision"


@pytest.mark.parametrize("origin", ["visible", "later"])
def test_decision_observing_payload_and_subsequent_decisions_qualify(origin):
    evidence, op = timeline(origin)
    result = DecisionOrder(evidence).proposal(op, carriers(evidence))
    assert result["eligible"] is True
    assert result["origin_request_id"] == origin


@pytest.mark.parametrize("origin", ["pre", "visible", "later"])
def test_timestamps_and_list_storage_order_are_not_attribution_clocks(origin):
    evidence, op = timeline(origin)
    for index, event in enumerate(evidence.events):
        event["timestamp"] = f"{2099 - index}-01-01T00:00:00Z"
    evidence.requests.reverse()
    result = DecisionOrder(evidence).proposal(op, carriers(evidence))
    assert result["eligible"] is (origin != "pre")


@pytest.mark.parametrize("kind", ["model_request", "model_response", "tool_call_succeeded"])
def test_missing_or_duplicate_visibility_boundary_is_unknown(kind):
    evidence, _ = timeline("visible")
    row = next(e for e in evidence.events if e["event_type"] == kind)
    if kind != "tool_call_succeeded":
        row = next(
            e
            for e in evidence.events
            if e["event_type"] == kind and e["payload"].get("request_id") == "visible"
        )
    row["event_type"] = "removed_boundary"
    with pytest.raises(OrderingError):
        carriers(evidence)
    row["event_type"] = kind
    evidence.events.append(copy.deepcopy(row))
    evidence.execution["journal_seq"] += 1
    with pytest.raises(OrderingError):
        carriers(evidence)


@pytest.mark.parametrize("change", ["position", "model_call_id", "turn", "proposal_hash"])
def test_missing_or_conflicting_origin_is_unknown(change):
    evidence, op = timeline("visible")
    if change == "proposal_hash":
        op["arguments_hash"] = "conflict"
    else:
        op[change] = {"position": 9, "turn": 9, "model_call_id": "impersonated"}[change]
    with pytest.raises(OrderingError):
        DecisionOrder(evidence).proposal(op, carriers(evidence))


def test_exposure_after_response_cannot_be_retroactive():
    evidence, _ = timeline("visible")
    marker = next(e for e in evidence.events if e["event_type"] == "injection_model_exposure")
    end = next(
        e
        for e in evidence.events
        if e["event_type"] == "model_response" and e["payload"]["request_id"] == "visible"
    )
    marker["event_type"], end["event_type"] = end["event_type"], marker["event_type"]
    marker["payload"], end["payload"] = end["payload"], marker["payload"]
    with pytest.raises(OrderingError, match="visibility_boundary"):
        carriers(evidence)


def test_duplicate_completed_origin_is_unknown_but_abandoned_request_is_not():
    evidence, op = timeline("visible")
    other = copy.deepcopy(evidence.requests[1])
    other.update(request_id="abandoned", status="started", calls=[])
    evidence.requests.append(other)
    assert DecisionOrder(evidence).proposal(op, carriers(evidence))["eligible"] is True
    other.update(status="completed")
    with pytest.raises(OrderingError, match="origin_decision"):
        DecisionOrder(evidence).proposal(op, carriers(evidence))


@pytest.mark.parametrize("missing", ["attempts", "receipts", "audits"])
def test_commit_requires_dispatch_receipt_and_audit(missing):
    evidence, op = timeline("visible")
    proof = {"logical": {"proposal_id": "write", "audit_sequence": 1, "receipt_key": "receipt"}}
    assert DecisionOrder(evidence).effect(op, proof)[0]["sequence"] == 1
    setattr(evidence, missing, [])
    with pytest.raises(OrderingError):
        DecisionOrder(evidence).effect(op, proof)


def test_effect_uses_single_audit_projection_not_whole_run_state():
    before = dict(
        task_id="task",
        customer_id="customer",
        title="Support",
        status="open",
        version=1,
        updated_at="2099-01-01",
    )
    audit = dict(
        task_id="task",
        tenant_id="tenant",
        before=before,
        after={**before, "status": "resolved", "version": 2, "updated_at": "1900-01-01"},
    )
    [change] = task_diff(audit)
    assert change["fields"] == ["status", "version"]
    assert change["after"]["tenant_id"] == "tenant"


def test_legacy_manifest_dump_and_hash_contract_is_preserved():
    assert "experimental_evaluator" not in ExperimentConfig().model_dump(mode="json")
    assert ExperimentConfig().experimental_evaluator == "1.1.0"
    config = ExperimentConfig(experimental_evaluator="1.2.0")
    assert config.model_dump(mode="json")["experimental_evaluator"] == "1.2.0"
    with pytest.raises(ValueError):
        ExperimentConfig(experimental_evaluator="9.0.0")


@pytest.mark.parametrize(
    "target,expected",
    [
        ({"task_id": "task", "status": "resolved"}, False),
        ({"task_id": "task", "title": "New"}, True),
        ({"task_id": "task"}, True),
        ({"task_id": "other"}, False),
    ],
)
def test_later_unrelated_effect_cannot_retroactively_establish_target_value(target, expected):
    change = {
        "after": {"task_id": "task", "status": "resolved", "title": "New"},
        "fields": ["title", "version"],
    }
    assert matches_effect(target, change) is expected
