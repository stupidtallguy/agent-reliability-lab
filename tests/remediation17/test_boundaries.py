import copy
import json

import pytest

from agent_reliability_lab.evaluation.attack_outcomes_v170 import resolve_trial
from agent_reliability_lab.evaluation.downloads import render_files
from agent_reliability_lab.evaluation.reporting import export, report
from agent_reliability_lab.research.identity import UnverifiableImplementation, require_compatible

from .support import facts, store


@pytest.mark.parametrize("damage", ["facts", "categories", "references", "goal", "goals"])
def test_malformed_objective_boundaries_are_unknown(damage):
    _, result = facts()
    goal = result.experimental["objectives"][0]
    if damage == "facts":
        result.experimental["attack_resolution"]["execution_facts"] = []
    elif damage == "categories":
        goal["attribution"]["diagnostic_categories"] = [None]
    elif damage == "references":
        goal["attribution"]["matched_proposal_ids"] = None
    elif damage == "goal":
        result.experimental["objectives"] = [None]
    else:
        result.experimental["objectives"] = {}
    resolved = resolve_trial(result)
    assert resolved["outcome"] is None and resolved["unknown_reasons"]


@pytest.mark.parametrize(
    "field", ["scoring_implementation_hash", "dependency_lock_hash", "implementation_scope"]
)
def test_present_but_invalid_identity_cannot_compare(field):
    _, result = facts()
    result.scoring_provenance[field] = "unverifiable"
    with pytest.raises(UnverifiableImplementation):
        require_compatible([result])


@pytest.mark.parametrize(
    "damage", ["none", "list", "missing_status", "bad_status", "missing_evidence"]
)
def test_malformed_execution_retains_planned_population(damage):
    trial, result = facts()
    trial = copy.deepcopy(trial)
    if damage == "missing_evidence":
        trial.pop("evidence")
    elif damage == "missing_status":
        trial["evidence"]["execution"].pop("status")
    elif damage == "bad_status":
        trial["evidence"]["execution"]["status"] = []
    else:
        trial["evidence"]["execution"] = None if damage == "none" else []
    document = report(store([(trial, result)]), "a" * 32, evaluator_version="1.7.0")
    census = document["summary"]["security"]["attack_outcome_coverage"]
    assert census["configured_attack_trials"] == census["unknown_trials"] == 1
    assert census["determinate_trials"] == census["unexposed_controls"] == 0
    assert census["attack_success"]["value"] is None


def test_downloads_equal_persisted_candidate_exports(tmp_path):
    document = report(store([facts()]), "a" * 32, evaluator_version="1.7.0")
    summary = document["summary"]
    scenario = next(iter(summary["per_scenario"].values()))
    summary["per_scenario"] = {"zz_case": scenario, "aa_case": scenario}
    objective = next(iter(summary["security"]["per_objective"].values()))
    summary["security"]["per_objective"] = {"zz_objective": objective, "aa_objective": objective}
    destination = export(document, tmp_path)
    for name, content in render_files(document).items():
        assert (destination / name).read_bytes() == content
    serialized = json.loads((destination / "results.json").read_bytes())
    assert render_files(serialized) == render_files(document)


@pytest.mark.parametrize("envelope", [None, [], {}])
def test_invalid_experiment_envelope_preserves_known_inventory(envelope):
    data = store([facts()])
    data.record = envelope
    doc = report(data, "a" * 32, evaluator_version="1.7.0")
    census = doc["summary"]["security"]
    assert census["population"]["materialized_trials"] == 1
    assert census["attack_outcome_coverage"]["configured_attack_trials"] is None
    assert doc["summary"]["metadata_error"]


def test_missing_trial_cleanup_is_not_a_reporting_crash():
    data = store([facts()])
    data.trials[0].pop("cleanup")
    doc = report(data, "a" * 32, evaluator_version="1.7.0")
    assert list(doc["cleanup"].values()) == [{"status": "unavailable"}]


def test_duplicate_materialized_slot_cannot_choose_a_successful_alias():
    data = store([facts()])
    data.trials.append(copy.deepcopy(data.trials[0]))
    document = report(data, "a" * 32, evaluator_version="1.7.0")
    census = document["summary"]["security"]["attack_outcome_coverage"]
    assert census["determinate_trials"] == 0 and census["unknown_trials"] == 1
    slot = document["summary"]["security"]["population"]["slots"][0]
    assert slot["classification"] == "contradictory_materialized_trial_identity"


@pytest.mark.parametrize("status", [[], {}])
def test_unhashable_objective_status_is_indeterminate(status):
    _, result = facts()
    result.experimental["objectives"][0]["attribution"]["status"] = status
    resolved = resolve_trial(result)
    assert resolved["outcome"] is None
    assert "missing_or_unsupported_attribution_status" in resolved["unknown_reasons"]


def test_report_rejects_score_with_unrelated_capture_hash():
    trial, result = facts()
    result.evidence_hash = "f" * 64
    with pytest.raises(ValueError, match="score/capture hash mismatch"):
        report(store([(trial, result)]), "a" * 32, evaluator_version="1.7.0")


@pytest.mark.parametrize("contradictory", [False, True])
def test_candidate_attack_breakdowns_use_verified_population(contradictory):
    trial, result = facts()
    if contradictory:
        result.experimental["objectives"][0]["attribution"]["status"] = "verified_non_match"
    summary = report(store([(trial, result)]), "a" * 32, evaluator_version="1.7.0")["summary"]
    expected = None if contradictory else 1.0
    assert summary["security"]["per_objective"]["workflow_hijack"]["value"] == expected
    for level in (summary, *summary["per_scenario"].values(), *summary["per_category"].values()):
        assert level["metrics"]["prompt_injection_attack_success_rate"]["value"] == expected
