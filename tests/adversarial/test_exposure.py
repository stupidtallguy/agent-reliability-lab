"""Small deterministic stage-chain controls, independent of PostgreSQL."""

import copy
from types import SimpleNamespace

import pytest
from conftest import configuration

from agent_reliability_lab.adversarial.exposure import verify
from agent_reliability_lab.opsdesk.fixtures import digest


def evidence():
    harness = configuration().harnesses["attack_body_answer"]
    plan = harness.runtime()
    spec = plan.attacks[0]
    config_hash = digest(spec.model_dump(mode="json"))
    base = {
        "injection_id": spec.injection_id,
        "configuration_hash": config_hash,
        "tool_call_id": "proposal",
        "attempt_id": "attempt",
        "logical_operation_id": None,
    }

    def event(kind, **fields):
        return {"sequence": 0, "event_type": kind, "payload": {**base, **fields}}

    events = [
        event("injection_trigger", matched=True, dispatch_ordinal=1),
        event(
            "injection_activated",
            boundary="before_output_validation",
            underlying_executed=True,
            underlying_success=True,
            transformed_response_hash="hash",
        ),
        event("injection_observed", observed_response_hash="hash", payload_delivered=True),
        event("tool_call_succeeded", response_hash="hash"),
        event("model_request", request_id="request", input_hash="input"),
        event(
            "injection_model_exposure",
            request_id="request",
            input_hash="input",
            observed_response_hash="hash",
        ),
    ]
    for i, e in enumerate(events, 1):
        e["sequence"] = i
    return SimpleNamespace(
        experimental={
            "harness": harness.model_dump(mode="json"),
            "harness_hash": digest(harness.model_dump(mode="json")),
            "runtime_hash": digest(plan.model_dump(mode="json")),
            "defense": {"configuration": "baseline"},
        },
        execution={
            "config": {
                "runtime_plan": plan.model_dump(mode="json"),
                "defense": {"configuration": "baseline"},
            }
        },
        attempts=[{"attempt_id": "attempt", "proposal_id": "proposal", "status": "succeeded"}],
        operations=[
            {
                "proposal_id": "proposal",
                "operation_id": None,
                "tool": "get_document",
                "arguments": {"document_id": "policy_001"},
            }
        ],
        requests=[{"request_id": "request", "status": "completed"}],
        events=events,
    )


def test_complete_chain_exposed():
    _, records, errors = verify(evidence())
    assert not errors
    assert records[0]["exposed"] is True


@pytest.mark.parametrize(
    "kind",
    [
        "injection_trigger",
        "injection_activated",
        "injection_observed",
        "injection_model_exposure",
        "tool_call_succeeded",
        "model_request",
    ],
)
def test_missing_stage_inconclusive(kind):
    e = evidence()
    e.events = [v for v in e.events if v["event_type"] != kind]
    _, _, errors = verify(e)
    assert errors


@pytest.mark.parametrize(
    "kind,key,value",
    [
        ("injection_trigger", "matched", False),
        ("injection_trigger", "dispatch_ordinal", 2),
        ("injection_activated", "configuration_hash", "wrong"),
        ("injection_activated", "logical_operation_id", "forged"),
        ("injection_observed", "observed_response_hash", "different"),
        ("injection_model_exposure", "request_id", "unknown"),
        ("injection_model_exposure", "input_hash", "different"),
        ("injection_model_exposure", "observed_response_hash", "different"),
    ],
)
def test_conflicting_stage_rejected(kind, key, value):
    e = evidence()
    next(v for v in e.events if v["event_type"] == kind)["payload"][key] = value
    assert verify(e)[2]


@pytest.mark.parametrize("key", ["harness_hash", "runtime_hash"])
def test_config_hash_binding(key):
    e = evidence()
    e.experimental[key] = "0" * 64
    assert "experimental_configuration_mismatch" in verify(e)[2]


def test_failed_model_delivery_is_unknown():
    e = evidence()
    e.requests[0]["status"] = "started"
    _, records, errors = verify(e)
    assert not errors
    assert records[0]["exposed"] is None


def test_result_size_rejection_is_unexposed():
    e = evidence()
    e.events = [v for v in e.events if v["event_type"] != "injection_model_exposure"]
    obs = next(v for v in e.events if v["event_type"] == "injection_observed")
    obs["payload"].update(payload_delivered=False, observed_response_hash="size_error")
    end = next(v for v in e.events if v["event_type"] == "tool_call_succeeded")
    end["payload"]["response_hash"] = "size_error"
    _, records, errors = verify(e)
    assert not errors and records[0]["exposed"] is False


def test_no_subsequent_model_call_means_no_model_exposure():
    e = evidence()
    e.events = [
        v for v in e.events if v["event_type"] not in {"model_request", "injection_model_exposure"}
    ]
    e.requests = []
    _, records, errors = verify(e)
    assert not errors and records[0]["exposed"] is False


def test_repeated_activation_above_cap_rejected():
    e = evidence()
    e.events.append(copy.deepcopy(e.events[1]))
    assert any("activation_limit" in v for v in verify(e)[2])


def test_never_reached_is_distinct_from_missing_trigger():
    e = evidence()
    e.events = []
    e.attempts = []
    e.operations = []
    _, records, errors = verify(e)
    assert not errors and records[0]["exposed"] is False
