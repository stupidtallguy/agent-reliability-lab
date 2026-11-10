import copy
import csv
import json

import pytest

from agent_reliability_lab.evaluation.attack_outcomes import resolve_trial
from agent_reliability_lab.evaluation.execution_facts import execution_facts
from agent_reliability_lab.evaluation.reporting import export, report
from agent_reliability_lab.opsdesk.fixtures import digest
from tests.finalization.population_support import Store
from tests.finalization.population_support import facts as historical_facts

from .support import configuration


def facts(outcome=True, exposure=True, index=1):
    t, r = historical_facts(outcome, exposure, index, version="1.6.0")
    goal = r.experimental["objectives"][0]
    goal["injection_id"] = configuration().harnesses["attack_hijack"].attacks[0].injection_id
    goal["verified_exposure"] = exposure
    goal["attribution"]["status"] = (
        "verified_unexposed_completed"
        if exposure is False
        else "eligible_match"
        if outcome
        else "verified_non_match"
        if outcome is False
        else "indeterminate"
    )
    r.experimental["attack_resolution"] = resolve_trial(r, facts=execution_facts(t["evidence"]))
    return t, r


def store(rows, repeats=1, empty=False):
    return Store(rows, repeats, version="1.6.0", empty=empty)


@pytest.mark.parametrize(
    "path,value,classification",
    [
        (["execution"], None, "missing_execution"),
        (["execution"], [], "malformed_execution"),
        (["execution", "status"], None, "malformed_execution"),
        (["execution", "status"], {}, "malformed_execution"),
        (["execution", "result"], [], "malformed_execution"),
        (["execution", "result", "resume_eligible"], "false", "malformed_execution"),
        (["execution", "result", "status"], "running", "contradictory_evidence"),
        (["events"], None, "malformed_execution"),
        (["events"], [{}], "malformed_execution"),
    ],
)
def test_malformed_execution_cannot_remove_manifest_slots(path, value, classification):
    t, r = facts()
    capture = t["evidence"]
    target = capture
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    t["evidence_hash"] = digest(capture)
    d = report(store([(t, r)]), "a" * 32)
    security = d["summary"]["security"]
    slot = security["population"]["slots"][0]
    coverage = security["attack_outcome_coverage"]
    assert slot["classification"] == classification
    assert coverage["configured_attack_trials"] == coverage["unknown_trials"] == 1
    assert coverage["determinate_trials"] == coverage["unexposed_controls"] == 0
    assert (
        d["summary"]["metrics"]["prompt_injection_attack_success_rate"]
        == coverage["attack_success"]
    )


@pytest.mark.parametrize(
    "outcome,exposure,expected,controls",
    [
        (True, True, True, 0),
        (False, True, False, 0),
        (None, True, None, 0),
        (None, None, None, 0),
        (None, False, None, 1),
    ],
)
def test_canonical_single_objective_and_denominators(outcome, exposure, expected, controls):
    d = report(store([facts(outcome, exposure)]), "a" * 32)
    c = d["summary"]["security"]["attack_outcome_coverage"]
    assert c["unexposed_controls"] == controls
    assert c["attack_success"]["value"] == (None if expected is None else int(expected))
    assert c["attack_success"] == d["summary"]["metrics"]["prompt_injection_attack_success_rate"]


@pytest.mark.parametrize("contradictory,expected", [(False, True), (True, None)])
def test_success_plus_uncertainty_has_one_explicit_policy(contradictory, expected):
    t, r = facts()
    other = copy.deepcopy(r.experimental["objectives"][0])
    other.update(injection_id="second", success=None)
    other["attribution"].update(
        status="indeterminate",
        diagnostic_categories=["contradictory"] if contradictory else ["missing"],
    )
    r.experimental["objectives"].append(other)
    # This test targets the canonical resolver; population additionally pins configured IDs.
    resolved = resolve_trial(r)
    assert resolved["outcome"] is expected
    assert resolved["policy"] == "any_objective_with_contradiction_veto_v1"
    assert bool(resolved["unknown_reasons"]) is contradictory


def test_planned_unmaterialized_slots_and_empty_experiment():
    d = report(store([facts()], repeats=3), "a" * 32)
    c = d["summary"]["security"]["attack_outcome_coverage"]
    assert c["configured_attack_trials"] == 3 and c["unknown_trials"] == 2
    assert c["coverage"]["value"] == pytest.approx(1 / 3)
    c = report(store([], empty=True), "a" * 32)["summary"]["security"]["attack_outcome_coverage"]
    assert c["configured_attack_trials"] == 0 and c["attack_success"]["value"] is None


def test_exports_use_identical_canonical_asr(tmp_path):
    d = report(store([facts(None, True)]), "a" * 32)
    path = export(d, tmp_path)
    j = json.loads((path / "results.json").read_text())
    md = (path / "report.md").read_text()
    assert json.loads(md.split("```json\n")[1].split("\n```")[0]) == j["summary"]["security"]
    rows = list(csv.DictReader((path / "metrics.csv").open()))
    general = next(
        r
        for r in rows
        if r["scenario_id"] == "__all__" and r["metric"] == "prompt_injection_attack_success_rate"
    )
    security = next(
        r
        for r in rows
        if r["scenario_id"] == "__security__" and r["metric"] == "attack_outcome_attack_success"
    )
    for field in ("value", "numerator", "denominator", "status", "reason"):
        assert general[field] == security[field]
    assert general["reason"] == "no_determinate_attack_outcomes"


@pytest.mark.parametrize("kind", ["hash_conflict", "missing_hash", "infrastructure"])
def test_integrity_and_infrastructure_failures_remain_accounted(kind):
    t, r = facts()
    if kind == "hash_conflict":
        t["evidence_hash"] = "f" * 64
    elif kind == "missing_hash":
        t["evidence_hash"] = None
    else:
        r.eligible = False
        r.status = "infrastructure_failure"
    d = report(store([(t, r)]), "a" * 32)
    c = d["summary"]["security"]["attack_outcome_coverage"]
    assert c["configured_attack_trials"] == c["unknown_trials"] == 1
    assert c["attack_success"]["denominator"] == 0 and c["measured_failures"] == 0
    assert c["attack_success"] == d["summary"]["metrics"]["prompt_injection_attack_success_rate"]


def test_resume_retains_stale_interrupted_result_without_hiding_verified_commit():
    t, r = facts()
    e = t["evidence"]
    e["execution"].update(
        status="running", result={"status": "interrupted", "resume_eligible": True}
    )
    f = execution_facts(e)
    assert f["classification"] == "incomplete_resumable" and not f["malformed"]
    assert resolve_trial(r, facts=f)["outcome"] is True


@pytest.mark.parametrize("contradiction,expected", [(False, 1.0), (True, None)])
def test_multi_objective_reports_share_one_resolution(contradiction, expected):
    t, r = facts()
    memory = store([(t, r)])
    cfg = memory.record["manifest"]["config"]
    attack = copy.deepcopy(cfg["harnesses"]["attack_hijack"]["attacks"][0])
    attack.update(
        injection_id="second_attack", tool="search_documents", surface="/data/items/0/snippet"
    )
    attack["trigger"]["arguments"] = {}
    cfg["harnesses"]["attack_hijack"]["attacks"].append(attack)
    memory.record["manifest_hash"] = digest(memory.record["manifest"])
    goal = copy.deepcopy(r.experimental["objectives"][0])
    goal.update(injection_id="second_attack", success=None)
    goal["attribution"].update(
        status="indeterminate",
        diagnostic_categories=["contradictory"] if contradiction else ["missing"],
    )
    r.experimental["objectives"].append(goal)
    d = report(memory, "a" * 32)
    general = d["summary"]["metrics"]["prompt_injection_attack_success_rate"]
    security = d["summary"]["security"]["attack_outcome_coverage"]["attack_success"]
    assert general == security and general["value"] == expected


def test_contradictory_objective_status_cannot_be_a_measured_result():
    t, r = facts()
    r.experimental["objectives"][0]["attribution"]["status"] = "verified_non_match"
    assert resolve_trial(r)["outcome"] is None
