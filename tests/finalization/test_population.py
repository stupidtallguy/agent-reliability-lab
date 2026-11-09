"""Controlled fact DTOs test accounting, independently of agent decision scripts."""

import copy
import csv
import json
import uuid

import pytest

from agent_reliability_lab.benchmarks.scenario import Scenario
from agent_reliability_lab.evaluation.contracts import Evidence, OracleSpec
from agent_reliability_lab.evaluation.population import population
from agent_reliability_lab.evaluation.reporting import export, report
from agent_reliability_lab.evaluation.scoring import score
from agent_reliability_lab.evaluation.selection import IncompatibleCohort
from agent_reliability_lab.opsdesk.fixtures import digest

from .support import ROOT, configuration


def facts(outcome, exposure, index=1, *, resume=False, eligible=True, version="1.5.0"):
    s = Scenario.model_validate_json(
        (ROOT / "benchmarks/development/normal_order_status.json").read_text()
    )
    e = Evidence.model_validate_json(
        (ROOT / "tests/evaluation/data/normal_order_status.json").read_text()
    )
    meta = dict(
        trial_id=uuid.UUID(int=index).hex,
        experiment_id="a" * 32,
        execution_id=e.execution_id,
        scenario_id=s.scenario_id,
        scenario_version=s.scenario_version,
        scenario_hash=digest(s.model_dump(mode="json")),
        category=s.category,
        split="development",
        trial_index=index,
        mode="scripted",
    )
    r = score(s, OracleSpec(), e, meta)
    r.evaluator_version = version
    r.scenario_id = "attack_hijack"
    r.scenario_hash = configuration().harnesses["attack_hijack"].scenario_hash
    r.trial_index = index
    r.eligible = eligible
    r.attack_eligible = exposure is True
    r.attacker_success = outcome
    r.scoring_provenance.update(
        requested_evaluator_version=version, effective_evaluator_version=version
    )
    if resume:
        e.execution.update(
            status="interrupted",
            result={**e.execution["result"], "status": "interrupted", "resume_eligible": True},
        )
    r.agent_status = e.execution["status"]
    goal = dict(
        injection_id="test_attack",
        objective="workflow_hijack",
        exposed=exposure is True,
        success=outcome,
        attribution={
            "status": "verified_unexposed_completed"
            if exposure is False
            else "eligible_match"
            if outcome
            else "indeterminate"
        },
    )
    r.experimental = dict(
        configuration="baseline",
        case_kind="attack",
        objectives=[goal],
        exposures=[dict(injection_id="test_attack", kind="attack", exposed=exposure)],
        verified_attack_exposure=exposure,
    )
    capture = e.model_dump(mode="json")
    t = dict(
        trial_id=r.trial_id,
        scenario_id=r.scenario_id,
        trial_index=index,
        evidence=capture,
        evidence_hash=digest(capture),
        cleanup={"status": "synthetic_unit_fixture"},
    )
    return t, r


class Store:
    def __init__(self, pairs, repeats=1, version="1.5.0", empty=False):
        cfg = configuration(repeats=repeats, experimental_evaluator=version)
        self.trials = [p[0] for p in pairs]
        self.results = {p[0]["trial_id"]: [p[1]] for p in pairs}
        manifest = dict(
            config=cfg.model_dump(mode="json"),
            cases=[]
            if empty
            else [
                dict(
                    scenario_id="attack_hijack",
                    scenario_hash=cfg.harnesses["attack_hijack"].scenario_hash,
                )
            ],
            purpose="scripted_infrastructure_validation",
        )
        self.record = dict(
            experiment_id="a" * 32, manifest=manifest, manifest_hash=digest(manifest)
        )

    def experiment(self, _):
        return self.record

    def list_trials(self, **kwargs):
        return self.trials

    def scores(self, identifier):
        return self.results[identifier]

    def save_report(self, *args):
        return "b" * 32


@pytest.mark.parametrize(
    "outcome,exposure,S,F,K,U,unknown,cov",
    [
        (True, True, 1, 0, 1, 0, 0, 1),
        (False, True, 0, 1, 1, 0, 0, 1),
        (None, True, 0, 0, 0, 0, 1, 0),
        (None, None, 0, 0, 0, 0, 1, 0),
        (None, False, 0, 0, 0, 1, 0, None),
    ],
)
def test_exact_attack_denominators(outcome, exposure, S, F, K, U, unknown, cov):
    store = Store([facts(outcome, exposure)])
    c = report(store, "a" * 32)["summary"]["security"]["attack_outcome_coverage"]
    assert (
        c["measured_successes"],
        c["measured_failures"],
        c["determinate_trials"],
        c["unexposed_controls"],
        c["unknown_trials"],
    ) == (S, F, K, U, unknown)
    assert c["coverage"]["value"] == cov
    assert c["attack_success"]["denominator"] == K
    assert c["attack_success"]["value"] == (S / K if K else None)


@pytest.mark.parametrize("materialized", [0, 1])
def test_manifest_census_includes_never_materialized_slots(materialized):
    store = Store([facts(True, True)] if materialized else [], repeats=3)
    doc = report(store, "a" * 32)
    p = doc["summary"]["security"]["population"]
    c = doc["summary"]["security"]["attack_outcome_coverage"]
    assert p["planned_trials"] == 3 and p["materialized_trials"] == materialized
    assert p["unmaterialized_trials"] == 3 - materialized
    assert c["configured_attack_trials"] == 3 and c["unknown_trials"] == 3 - materialized
    assert c["coverage"]["value"] == materialized / 3
    assert len(store.trials) == materialized  # No invented executions/trials.


def test_resumable_execution_cannot_be_a_completed_control():
    store = Store([facts(True, True), facts(None, False, 2, resume=True)], repeats=2)
    c = report(store, "a" * 32)["summary"]["security"]["attack_outcome_coverage"]
    assert c["unexposed_controls"] == 0 and c["unknown_trials"] == 1
    assert c["coverage"]["value"] == 0.5


def test_explicit_nonresumable_interruption_is_not_overridden_by_status():
    trial, result = facts(None, False, resume=True)
    trial["evidence"]["execution"]["result"]["resume_eligible"] = False
    trial["evidence_hash"] = digest(trial["evidence"])
    pop = population(Store([(trial, result)]).record, [trial], [result])
    slot = pop["slots"][0]
    assert slot["classification"] == "interrupted_nonresumable"
    assert slot["resume_eligible"] is False
    assert slot["exposure"] is None and slot["completed"] is False


def test_infrastructure_exclusion_cannot_be_measured_success():
    pair = facts(True, True, eligible=False)
    pair[1].status = "infrastructure_failure"
    doc = report(Store([pair]), "a" * 32)
    assert doc["summary"]["metrics"]["prompt_injection_attack_success_rate"]["value"] is None
    assert doc["summary"]["security"]["attack_outcome_coverage"]["measured_successes"] == 0


def test_empty_and_unavailable_plan_are_different():
    d = report(Store([], empty=True), "a" * 32)
    assert d["summary"]["security"]["configured_trials"] == 0
    assert d["summary"]["security"]["attack_outcome_coverage"]["coverage"]["value"] is None
    assert population(None, [], [])["planned_trials"] is None


def test_missing_plan_counts_known_trial_references_without_a_sentinel():
    from types import SimpleNamespace

    results = [SimpleNamespace(trial_id="first"), SimpleNamespace(trial_id="second")]
    missing = population(None, [], results)
    assert missing["metadata_unavailable_trials"] == 2
    assert missing["planned_trials"] is None
    assert missing["selected_scores"] == 2


def test_missing_plan_without_observations_has_unknown_inventory():
    missing = population(None, [], [])
    assert missing["metadata_unavailable_trials"] is None
    assert missing["planned_trials"] is None


def test_homogeneous_historical_rescore_selects_historical_report_semantics():
    store = Store([facts(True, True, version="1.1.0")])
    doc = report(store, "a" * 32)
    assert doc["selection"]["evaluator_version"] == "1.1.0"
    assert doc["summary"]["security"]["configured_trials"] == 1
    assert "population" not in doc["summary"]["security"]


def test_mixed_versions_reject_and_explicit_revision_selection_is_supported():
    a, b = facts(True, True), facts(False, True, 2, version="1.1.0")
    store = Store([a, b], repeats=2)
    with pytest.raises(IncompatibleCohort):
        report(store, "a" * 32)
    doc = report(store, "a" * 32, evaluator_version="1.5.0")
    assert len(doc["results"]) == 1 and len(doc["selection"]["unavailable"]) == 1
    selected = report(store, "a" * 32, scoring_ids=[a[1].scoring_id])
    assert selected["results"][0]["scoring_id"] == a[1].scoring_id
    assert a[1].evaluator_version == "1.5.0" and b[1].evaluator_version == "1.1.0"


def test_exports_parse_to_identical_population_and_metric_records(tmp_path):
    doc = report(
        Store([facts(True, True), facts(False, True, 2), facts(None, None, 3)], repeats=4), "a" * 32
    )
    before = copy.deepcopy(doc)
    path = export(doc, tmp_path)
    json_doc = json.loads((path / "results.json").read_text())
    md = (path / "report.md").read_text()
    assert (
        json.loads(md.split("```json\n", 1)[1].split("\n```", 1)[0])
        == json_doc["summary"]["security"]
    )
    assert "unknown of" not in md
    rows = {
        (r["scenario_id"], r["metric"]): r for r in csv.DictReader((path / "metrics.csv").open())
    }
    p = json_doc["summary"]["security"]["population"]
    for key in (
        "planned_trials",
        "materialized_trials",
        "unmaterialized_trials",
        "eligible_trials",
        "excluded_trials",
    ):
        assert int(rows[("__population__", key)]["value"]) == p[key]
    c = json_doc["summary"]["security"]["attack_outcome_coverage"]
    for name in ("coverage", "attack_success"):
        r = rows[("__security__", "attack_outcome_" + name)]
        for field in ("numerator", "denominator", "value", "status", "reason"):
            assert r[field] == ("" if c[name][field] is None else str(c[name][field]))
    assert doc == before


def test_equal_version_different_adversarial_implementation_rejected():
    from agent_reliability_lab.evaluation.selection import compatible

    _, first = facts(True, True, 1)
    _, second = facts(False, True, 2)
    first.scoring_provenance["adversarial_source_hash"] = "a" * 64
    second.scoring_provenance["adversarial_source_hash"] = "b" * 64
    with pytest.raises(IncompatibleCohort, match="implementation hashes differ"):
        compatible([first, second])


def test_different_transitive_implementation_identity_rejects_cohort():
    from agent_reliability_lab.evaluation.selection import compatible

    _, first = facts(True, True, 1)
    _, second = facts(False, True, 2)
    first.scoring_provenance["scoring_implementation_hash"] = "a" * 64
    second.scoring_provenance["scoring_implementation_hash"] = "b" * 64
    with pytest.raises(IncompatibleCohort, match="implementation hashes differ"):
        compatible([first, second])
