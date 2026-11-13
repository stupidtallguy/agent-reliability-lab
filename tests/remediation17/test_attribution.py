import copy
import json

import pytest

from agent_reliability_lab.evaluation.contracts import Evidence
from tests.finalization.support import ANSWER, DOC, WRITE
from tests.remediation16.support import evaluate, reseal

from .support import configuration

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def control(lab, sid="attack_hijack"):
    config = configuration()
    if sid == "attack_hijack":
        config.scripts[sid] = copy.deepcopy([DOC, WRITE, ANSWER])
    t, r = await lab[1](sid, config=config)
    assert r.attacker_success is True, r.model_dump_json()
    return t, Evidence.model_validate_json(json.dumps(t["evidence"]))


@pytest.mark.parametrize("status", ["failed", "rejected", "pending", "retry"])
async def test_read_logical_state_conflict_is_not_success(lab, status):
    t, e = await control(lab, "attack_body_answer")
    e.operations[0]["status"] = status
    r = evaluate(t, e, version="1.7.0")
    assert r.attacker_success is None
    assert r.experimental["objectives"][0]["attribution"]["errors"] == [
        "contradictory_logical_operation_status"
    ]
    assert evaluate(t, e, version="1.6.0").attacker_success is True


@pytest.mark.parametrize(
    "damage,code",
    [
        ("input", "contradictory_sealed_request_input_hash"),
        ("missing", "missing_or_malformed_sealed_input_hash"),
        ("order", "contradictory_sealed_decision_order"),
        ("owner", "contradictory_sealed_request_execution"),
    ],
)
async def test_sealed_request_relationships(lab, damage, code):
    t, e = await control(lab)
    marker = next(v for v in e.events if v["event_type"] == "injection_model_exposure")
    rid = marker["payload"]["request_id"]
    start = next(r for r in e.provenance if r["kind"] == "model_started" and r["reference"] == rid)
    if damage == "input":
        start["body"]["input_hash"] = "f" * 64
    elif damage == "missing":
        start["body"].pop("input_hash")
    elif damage == "owner":
        start["body"]["execution_id"] = "f" * 32
    else:
        end = next(
            r for r in e.provenance if r["kind"] == "model_completed" and r["reference"] == rid
        )
        e.provenance.remove(end)
        e.provenance.insert(e.provenance.index(start), end)
    reseal(e)
    result = evaluate(t, e, version="1.7.0")
    assert result.attacker_success is None
    assert result.experimental["objectives"][0]["attribution"]["errors"] == [code]


@pytest.mark.parametrize(
    "field,value,diagnostic",
    [
        ("arguments_hash", "f" * 64, "missing_or_contradictory_proposal_journal_arguments_hash"),
        ("tool", "get_order", "missing_or_contradictory_proposal_journal_tool"),
        (
            "logical_operation_id",
            "f" * 32,
            "missing_or_contradictory_proposal_journal_logical_operation_id",
        ),
        ("turn", -1, "missing_or_contradictory_request_journal_turn"),
    ],
)
async def test_consistently_resealed_journal_must_match_decision_and_proposal(
    lab, field, value, diagnostic
):
    trial, evidence = await control(lab)
    event_type = "model_request" if field == "turn" else "tool_call_proposed"
    event = next(row for row in evidence.events if row["event_type"] == event_type)
    record = next(
        row
        for row in evidence.provenance
        if row["kind"] == "journal_event" and row["body"]["sequence"] == event["sequence"]
    )
    record["body"]["payload"][field] = value
    if field != "turn":
        event["payload"][field] = value
    reseal(evidence)
    result = evaluate(trial, evidence, version="1.7.0")
    assert result.attacker_success is None
    assert result.experimental["objectives"][0]["attribution"]["errors"] == [diagnostic]
