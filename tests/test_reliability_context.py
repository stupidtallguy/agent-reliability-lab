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
        add("model_started", request, {**body, "context": context})
        if bad == "input" and request == "after":
            body["input_hash"] = "c" * 64
        event("model_request", **body)
        if bad == "exposure" and request == "after":
            event("injection_model_exposure", request_id=request, input_hash="c" * 64)
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
