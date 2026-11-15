import pytest

from agent_reliability_lab.agent.config import ModelConfig
from agent_reliability_lab.agent.provenance import seal
from agent_reliability_lab.reliability.context import compare_requests, fingerprints


def ledger(*, changed=False, bad=None, resumed=False):
    records = []

    def add(kind, reference, body):
        records.append(
            seal(
                "run",
                len(records) + 1,
                kind,
                reference,
                body,
                records[-1]["record_hash"] if records else None,
            )
        )

    def event(name, **payload):
        add(
            "journal_event",
            name,
            dict(event_type=name, execution_id="run", sequence=len(records), payload=payload),
        )

    add("execution_created", "run", {})
    for request in ("before", "after"):
        if request == "after" and resumed:
            event("run_resumed")
        later = changed and request == "after"
        body = dict(
            request_id=request,
            execution_id="run",
            turn=int(later),
            provider="fake",
            model="demo",
            input_hash=("b" if later else "a") * 64,
        )
        if bad == "missing_hash" and request == "after":
            del body["input_hash"]
        model = ModelConfig(model_id="second" if later else "first")
        document = '{"data":{"document_id":"POLICY","version":"2"}}' if later else "{}"
        context = fingerprints(
            [{"role": "system", "content": str(later)}, {"role": "tool", "content": document}],
            model,
            max_output_tokens=10,
        )
        context["tool_schema_hash"] = "d" * 64
        add("model_started", request, {**body, "context": context})
        if bad == "input" and request == "after":
            body["input_hash"] = "c" * 64
        event("model_request", **body)
        if bad == "exposure" and request == "after":
            event("injection_model_exposure", request_id=request, input_hash="c" * 64)
        if changed or request == "after":
            add("model_completed", request, body)
    return records


def test_same_request_is_distinct_from_same_turn_model_retry():
    records = ledger()
    assert compare_requests(records, "run", "before", "before")["boundary"] == "same_request"
    comparison = compare_requests(records, "run", "before", "after")
    assert (comparison["relation"], comparison["boundary"]) == (
        "identical",
        "same_turn_model_retry",
    )


def test_changed_request_identifies_observation_model_and_instruction_drift_after_resume():
    result = compare_requests(ledger(changed=True, resumed=True), "run", "before", "after")
    assert (result["relation"], result["boundary"], result["resumed_between"]) == (
        "changed",
        "new_decision",
        True,
    )
    assert result["changes"] == ["instructions_hash", "model_config_hash", "observations"]
    assert result["observations"]["current"][0]["documents"] == [
        {"document_id": "POLICY", "version": "2"}
    ]


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        ("input", "contradictory_input_boundary"),
        ("exposure", "contradictory_exposure_boundary"),
    ],
)
def test_sealed_but_contradictory_boundary_is_rejected(bad, reason):
    result = compare_requests(ledger(bad=bad), "run", "before", "after")
    assert (result["relation"], result["reason"]) == ("contradictory", reason)


def test_missing_or_modified_evidence_is_not_verified():
    records = ledger()
    result = compare_requests(records, "run", "before", "missing")
    assert result["reason"] == "missing_request_boundary"
    records[-1]["body"]["turn"] = 9
    assert compare_requests(records, "run", "before", "after")["relation"] == "contradictory"


def test_reversed_request_order_is_contradictory():
    result = compare_requests(ledger(), "run", "after", "before")
    assert result["reason"] == "contradictory_request_order"


def test_missing_input_hash_is_unverifiable():
    result = compare_requests(ledger(bad="missing_hash"), "run", "before", "after")
    assert (result["relation"], result["reason"]) == (
        "unverifiable",
        "missing_or_invalid_input_hash",
    )


def reseal(records):
    rebuilt = []
    for row in records:
        rebuilt.append(
            seal(
                "run",
                len(rebuilt) + 1,
                row["kind"],
                row["reference"],
                row["body"],
                rebuilt[-1]["record_hash"] if rebuilt else None,
            )
        )
    return rebuilt


@pytest.mark.parametrize(("first", "second"), [(0, -1), (3, 1)])
def test_invalid_turn_does_not_verify_context(first, second):
    records = ledger(changed=True)
    for row in records:
        body = row["body"]
        target = body.get("payload", body)
        if "turn" in target:
            target["turn"] = first if target["request_id"] == "before" else second
    assert compare_requests(reseal(records), "run", "before", "after")["reason"] == (
        "contradictory_model_turn"
    )


@pytest.mark.parametrize("component", ["instructions_hash", "observations", "tool_schema_hash"])
def test_identical_hash_cannot_disagree_on_input_component(component):
    records = ledger()
    start = next(row for row in records if row["reference"] == "after")
    start["body"]["context"][component] = [] if component == "observations" else "e" * 64
    result = compare_requests(reseal(records), "run", "before", "after")
    assert (result["relation"], result["reason"]) == (
        "contradictory",
        "contradictory_input_components",
    )


def test_independent_configuration_is_outside_input_hash():
    records = ledger()
    next(row for row in records if row["reference"] == "after")["body"]["context"][
        "model_config_hash"
    ] = "e" * 64
    result = compare_requests(reseal(records), "run", "before", "after")
    assert (result["relation"], result["changes"]) == ("identical", ["model_config_hash"])


def test_incomplete_components_and_duplicate_request_identity():
    records = ledger()
    start = next(row for row in records if row["reference"] == "after")
    del start["body"]["context"]["observations"]
    assert compare_requests(reseal(records), "run", "before", "after")["relation"] == "unverifiable"
    records.append(start)
    assert compare_requests(reseal(records), "run", "before", "after")["reason"] == (
        "contradictory_request_identity"
    )


@pytest.mark.parametrize(
    ("complete", "errors", "effects", "mapped", "expected"),
    [
        (True, [], ["receipt_confirmed"], True, "unknown"),
        (True, [], ["unknown", "receipt_confirmed"], True, "unknown"),
        (False, [{"code": "receipt_response_conflict"}], ["denied"], True, "contradictory"),
        (False, [], ["receipt_confirmed"], True, "unknown"),
        (True, [], ["denied"], True, "contradictory"),
        (False, [{"code": "successful_write_missing_receipt"}], ["unknown"], False, "unknown"),
        (True, [], [], True, "unknown"),
        (True, [], ["denied"], False, "denied"),
    ],
)
def test_retry_inspector_separates_observed_mutation_from_attribution(
    complete, errors, effects, mapped, expected
):
    from agent_reliability_lab.reliability.inspection import retry_chain

    evidence = {
        "operations": [
            {
                "proposal_id": "p",
                "operation_id": "w",
                "execution_id": "run",
                "turn": 0,
                "tool": "create_task",
            }
        ],
        "attempts": [
            {
                "proposal_id": "p",
                "attempt_id": str(i),
                "ordinal": i,
                "status": "succeeded",
                "effect": effect,
            }
            for i, effect in enumerate(effects, 1)
        ],
    }
    result = retry_chain(
        evidence,
        "p",
        {
            "complete": complete,
            "errors": errors,
            "committed": {"w": {"receipt_key": "r"}} if mapped else {},
        },
    )
    assert result["outcome"] == expected
    assert result["mutation_evidence"] == "unresolved"


def test_missing_receipt_can_show_an_observed_target_mutation():
    from agent_reliability_lab.reliability.inspection import retry_chain

    operation = {
        "proposal_id": "p",
        "operation_id": "w",
        "execution_id": "run",
        "turn": 0,
        "tool": "update_task",
        "arguments": {"task_id": "target"},
    }
    evidence = {
        "operations": [operation],
        "execution": {"config": {"actor_id": "actor", "tenant_id": "tenant"}},
        "audits": [
            {
                "operation": "update_task",
                "task_id": "target",
                "actor_id": "actor",
                "tenant_id": "tenant",
            },
        ],
    }
    result = retry_chain(evidence, "p", {"complete": False, "committed": {}})
    assert (result["mutation_evidence"], result["outcome"]) == ("observed_on_target", "unknown")


@pytest.mark.parametrize("value", [None, "", "not-sha256", 123])
def test_malformed_required_input_hash_cannot_verify_equality(value):
    rows = ledger()
    for row in rows:
        if row["kind"] == "model_started":
            row["body"]["context"]["instructions_hash"] = value
    result = compare_requests(reseal(rows), "run", "before", "after")
    assert result["relation"] == "unverifiable"


def test_nonadjacent_turn_needs_intervening_sealed_decisions():
    initial = ledger(changed=True)
    start, request, decision = initial[-3:]
    for row in initial[-3:]:
        row["body"].get("payload", row["body"])["turn"] = 17
    missing = compare_requests(reseal(initial), "run", "before", "after")
    assert missing["reason"] == "missing_intervening_decision"

    from copy import deepcopy

    rows = initial[:-3]
    for turn in range(1, 17):
        for template in (start, request, decision):
            row = deepcopy(template)
            body = row["body"].get("payload", row["body"])
            body.update(request_id=f"model_{turn}", turn=turn)
            if row["kind"] == "journal_event":
                row["body"]["sequence"] = turn + 4
            else:
                row["reference"] = f"model_{turn}"
            rows.append(row)
    request["body"]["sequence"] = 21
    result = compare_requests(reseal(rows + [start, request, decision]), "run", "before", "after")
    assert result["relation"] == "changed"
    assert len(result["references"]) == 18


def test_committed_flag_with_denied_and_unresolved_attempts_is_not_verification():
    from agent_reliability_lab.reliability.inspection import retry_chain

    operation = {
        "proposal_id": "p",
        "execution_id": "e",
        "operation_id": "op",
        "tool": "create_task",
        "turn": 0,
    }
    attempts = [
        dict(proposal_id="p", attempt_id=str(i), ordinal=i, status="failed", effect=effect)
        for i, effect in enumerate(("denied", "unknown"), 1)
    ]
    result = retry_chain(
        {"operations": [operation], "attempts": attempts},
        "p",
        {"complete": True, "committed": {"op": {"receipt_key": "key"}}},
    )
    assert result["outcome"] == "unknown"
    assert result["mutation_evidence"] == "unresolved"
