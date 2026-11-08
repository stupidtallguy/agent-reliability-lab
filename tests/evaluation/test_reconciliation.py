import pytest

from agent_reliability_lab.evaluation.reconciliation import reconcile
from agent_reliability_lab.evaluation.scoring import score


def test_receipt_audit_and_final_state_join(write_data):
    scenario, _, evidence, _ = write_data
    result = reconcile(scenario, evidence)
    assert result["complete"] and result["mutation_count"] == 1
    assert len(result["committed"]) == 1
    assert next(iter(result["committed"].values()))["audit_sequence"] == 1


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("receipt", "successful_write_missing_receipt"),
        ("audit", "missing_or_conflicting_mutation_audit"),
        ("event", "journal_sequence_gap"),
        ("hash", "intent_argument_hash_mismatch"),
        ("request_hash", "receipt_argument_conflict"),
        ("audit_before", "audit_chain_conflict"),
        ("marker", "execution_context_mismatch"),
        ("fixture", "fixture_hash_mismatch"),
        ("counter", "attempt_counter_mismatch"),
        ("call", "proposal_model_correlation_mismatch"),
        ("access", "scenario_execution_binding_mismatch"),
    ],
)
def test_missing_and_conflicting_evidence(write_data, mutation, code):
    scenario, oracle, evidence, meta = write_data
    if mutation == "receipt":
        evidence.receipts.clear()
    elif mutation == "audit":
        evidence.audits.clear()
    elif mutation == "event":
        evidence.events.pop(2)
    elif mutation == "hash":
        evidence.operations[-1]["arguments_hash"] = "0" * 64
    elif mutation == "request_hash":
        evidence.receipts[0]["request_hash"] = "0" * 64
    elif mutation == "audit_before":
        evidence.audits[0]["before"]["title"] = "Different"
    elif mutation == "marker":
        evidence.marker = "wrong"
    elif mutation == "fixture":
        evidence.fixture_hash = "0" * 64
    elif mutation == "counter":
        evidence.execution["tool_calls"] += 1
    elif mutation == "call":
        evidence.operations[0]["model_call_id"] = "different"
    else:
        evidence.tool_access = {}
    reconciliation = reconcile(scenario, evidence)
    assert not reconciliation["complete"]
    assert code in {error["code"] for error in reconciliation["errors"]}
    result = score(scenario, oracle, evidence, meta)
    assert result.status == "evidence_error" and result.objective_success is None
    assert result.eligible
    assert all(finding.label != "infrastructure_failure" for finding in result.findings)


@pytest.mark.parametrize(
    "entity,record,field,value",
    [
        ("orders", "order_001", "status", "paid"),
        ("payments", "payment_001", "amount", "1.00"),
        ("actors", "actor_001", "role", "supervisor"),
        ("tasks", "task_001", "description", "Unexplained mutation"),
    ],
)
def test_full_state_catches_changes_outside_legacy_projection(
    normal_data, entity, record, field, value
):
    scenario, oracle, evidence, meta = normal_data
    evidence.final_full[entity][record][field] = value
    result = score(scenario, oracle, evidence, meta)
    assert result.status == "evidence_error" and result.objective_success is None
    assert any(
        error["code"] == "unexplained_full_state_mutation"
        for error in result.reconciliation["errors"]
    )


def test_pending_write_with_receipt_is_confirmed_even_without_completion_event(write_data):
    scenario, _, evidence, _ = write_data
    operation = next(op for op in evidence.operations if op["operation_id"])
    attempt = next(
        item for item in evidence.attempts if item["proposal_id"] == operation["proposal_id"]
    )
    operation.update(status="started", response=None)
    attempt.update(status="started", effect="unknown")
    removed = [
        event
        for event in evidence.events
        if event["event_type"] == "tool_call_succeeded"
        and event["payload"].get("attempt_id") == attempt["attempt_id"]
    ]
    assert len(removed) == 1
    evidence.events.remove(removed[0])
    for sequence, event in enumerate(evidence.events, 1):
        event["sequence"] = sequence
    evidence.execution["journal_seq"] = len(evidence.events)
    assert operation["operation_id"] in reconcile(scenario, evidence)["committed"]
