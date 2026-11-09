import copy

import pytest

from agent_reliability_lab.agent.errors import ExecutionInterrupted
from agent_reliability_lab.evaluation.reporting import report

from .support import ANSWER, DOC, WRITE, configuration, evaluate, frozen

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


def configured(sid="attack_hijack", **kwargs):
    c = configuration(**kwargs)
    c.scripts[sid] = copy.deepcopy([DOC, WRITE, ANSWER])
    return c


@pytest.mark.parametrize("sid", ["attack_hijack", "attack_viewer_attempt", "attack_body_answer"])
@pytest.mark.parametrize(
    "field", ["request_execution", "proposal_execution", "exposure_call", "exposure_order"]
)
async def test_common_gate_covers_all_objectives(lab, sid, field):
    _, run = lab
    c = configuration() if sid == "attack_body_answer" else configured(sid)
    _, [(trial, control)] = await run([sid], c)
    assert control.attacker_success is True, control.model_dump_json()
    e = frozen(trial)
    marker = next(v for v in e.events if v["event_type"] == "injection_model_exposure")
    if field == "request_execution":
        next(r for r in e.requests if r["request_id"] == marker["payload"]["request_id"])[
            "execution_id"
        ] = "conflicting"
    elif field == "proposal_execution":
        e.operations[0]["execution_id"] = "conflicting"
    elif field == "exposure_call":
        marker["payload"]["tool_call_id"] = "conflicting"
    else:
        marker["sequence"] = 1
    result = evaluate(trial, e)
    assert result.attacker_success is None, result.model_dump_json()
    assert result.experimental["objectives"][0]["attribution"]["diagnostic_categories"]


async def test_success_with_denial_errors_is_contradictory(lab):
    _, run = lab
    _, [(trial, valid)] = await run(["attack_hijack"], configured())
    assert valid.attacker_success is True
    e = frozen(trial)
    op = next(o for o in e.operations if o["tool"] == "update_task")
    attempt = next(a for a in e.attempts if a["proposal_id"] == op["proposal_id"])
    event = next(
        v
        for v in e.events
        if v["event_type"] == "tool_call_succeeded"
        and v["payload"].get("attempt_id") == attempt["attempt_id"]
    )
    attempt["error_code"] = event["payload"]["error_code"] = "permission_denied"
    result = evaluate(trial, e)
    assert result.attacker_success is None
    assert (
        "contradictory_attempt_status_error"
        in result.experimental["objectives"][0]["attribution"]["errors"]
    )
    assert len(e.audits) == len(e.receipts) == 1


@pytest.mark.parametrize("missing", [True, False])
async def test_dispatch_missing_and_conflicting_are_distinct(lab, missing):
    _, run = lab
    _, [(trial, _)] = await run(["attack_hijack"], configured())
    e = frozen(trial)
    op = next(o for o in e.operations if o["tool"] == "update_task")
    p = next(
        v["payload"]
        for v in e.events
        if v["event_type"] == "tool_call_started"
        and v["payload"]["tool_call_id"] == op["proposal_id"]
    )
    if missing:
        p.pop("tool")
    else:
        p["tool"] = "get_order"
    r = evaluate(trial, e)
    assert r.attacker_success is None
    assert (
        "missing_dispatch_tool" if missing else "contradictory_dispatch_tool"
    ) in r.experimental["objectives"][0]["attribution"]["errors"]


@pytest.mark.parametrize("batch", [True, False])
async def test_batched_decision_has_no_retroactive_eligibility(lab, batch):
    _, run = lab
    c = configured()
    if batch:
        c.scripts["attack_hijack"] = [{"calls": DOC["calls"] + WRITE["calls"]}, ANSWER]
    _, [(_, r)] = await run(["attack_hijack"], c)
    assert r.attacker_success is (not batch), r.model_dump_json()
    assert r.unsafe is True


async def test_receipt_proves_commit_despite_lost_response(lab):
    _, run = lab

    def interrupt(op, response):
        if op["tool"] == "update_task":
            raise ExecutionInterrupted("synthetic lost response")

    _, [(trial, r)] = await run(
        ["attack_hijack"], configured(), execution_options={"after_dispatch": interrupt}
    )
    assert r.attacker_success is True, r.model_dump_json()
    assert (
        "verified_committed_response_lost"
        in r.experimental["objectives"][0]["attribution"]["lifecycles"].values()
    )
    assert len(trial["evidence"]["receipts"]) == len(trial["evidence"]["audits"]) == 1


@pytest.mark.parametrize("version", ["1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0"])
async def test_manifest_declared_attack_cannot_fall_back_without_context(lab, version):
    runner, run = lab
    _, [(trial, _)] = await run(["attack_hijack"], configured())
    e = frozen(trial)
    e.experimental = None
    e.execution["config"]["runtime_plan"] = None
    r = evaluate(trial, e, version, runner.store.experiment(trial["experiment_id"]))
    assert r.status == "evidence_error" and r.attacker_success is None
    assert r.scoring_provenance["requested_evaluator_version"] == version
    assert r.scoring_provenance["effective_evaluator_version"] is None


async def test_resumable_nonexposure_stays_unresolved_in_population(lab):
    runner, run = lab
    exp, [(trial, r)] = await run(
        ["attack_hijack"], configured(), execution_options={"pause_before_tools": True}
    )
    doc = report(runner.store, exp)
    c = doc["summary"]["security"]["attack_outcome_coverage"]
    assert r.attacker_success is None and c["unexposed_controls"] == 0
    assert c["unknown_trials"] == 1 and c["coverage"]["denominator"] == 1
    assert c["coverage"]["value"] == 0
    assert (
        doc["summary"]["security"]["population"]["slots"][0]["classification"]
        == "incomplete_resumable"
    )
