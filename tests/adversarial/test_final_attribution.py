"""1.4 intent, version provenance and planned coverage without database access."""

import copy
import csv
import json
from pathlib import Path

import pytest

from agent_reliability_lab.adversarial.attribution_v140 import intent_relation
from agent_reliability_lab.adversarial.reporting import experimental_summary
from agent_reliability_lab.benchmarks.scenario import Scenario
from agent_reliability_lab.evaluation.contracts import Evidence, OracleSpec
from agent_reliability_lab.evaluation.experimental_context import (
    attach_plan,
    plan_for,
    unavailable_plan,
)
from agent_reliability_lab.evaluation.reporting import export
from agent_reliability_lab.evaluation.scoring import excluded, score
from agent_reliability_lab.evaluation.versions import UnsupportedEvaluatorVersion
from agent_reliability_lab.opsdesk.fixtures import digest

ROOT = Path(__file__).parents[2]


def case():
    scenario = Scenario.model_validate_json(
        (ROOT / "benchmarks/development/normal_order_status.json").read_text()
    )
    evidence = Evidence.model_validate_json(
        (ROOT / "tests/evaluation/data/normal_order_status.json").read_text()
    )
    meta = dict(
        trial_id="a" * 32,
        experiment_id="b" * 32,
        execution_id=evidence.execution_id,
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        scenario_hash=digest(scenario.model_dump(mode="json")),
        category=scenario.category,
        split="development",
        trial_index=1,
        mode="scripted",
    )
    return scenario, evidence, meta


@pytest.mark.parametrize(
    "args,expected",
    [
        ({}, "unverifiable"),
        ({"unsupported_parameter": "synthetic"}, "unverifiable"),
        ({"task_id": "task_001", "unsupported_parameter": "synthetic"}, "target_bearing"),
        ({"task_id": "task_001"}, "target_bearing"),
        ({"task_id": "task_002"}, "different_target"),
        ({"task_id": None}, "unverifiable"),
        ({"task_id": ""}, "unverifiable"),
    ],
)
def test_target_intent_requires_positive_evidence(args, expected):
    assert intent_relation({"task_id": "task_001"}, args) == expected


@pytest.mark.parametrize("version", ["1.1.0", "1.2.0", "1.3.0", "1.4.0"])
@pytest.mark.parametrize("damage", ["missing_turn", "missing_proposal", "missing_context"])
def test_requested_version_metadata_survives_early_errors(version, damage):
    scenario, evidence, meta = case()
    if damage == "missing_turn":
        evidence.operations[0].pop("turn")
    if damage == "missing_proposal":
        evidence.operations[0].pop("proposal_id")
    result = score(scenario, OracleSpec(), evidence, meta, experimental_evaluator=version)
    assert result.scoring_provenance["requested_evaluator_version"] == version
    if damage != "missing_context" or version == "1.4.0":
        assert result.status == "evidence_error"
        assert result.scoring_provenance["effective_evaluator_version"] is None
    if version == "1.4.0":
        assert result.evaluator_version == version
        assert result.experimental["context_error"] == "experimental_context_missing"
    elif damage != "missing_context":
        assert result.evaluator_version == "1.0.1"  # Historical label, explicit requested metadata.


def test_default_and_unsupported_selection_do_not_silently_change():
    scenario, evidence, meta = case()
    result = score(scenario, OracleSpec(), evidence, meta)
    assert result.scoring_provenance["requested_evaluator_version"] == "1.1.0"
    assert result.scoring_provenance["effective_evaluator_version"] == "1.0.1"
    with pytest.raises(UnsupportedEvaluatorVersion):
        score(scenario, OracleSpec(), evidence, meta, experimental_evaluator="1.7.0")
    with pytest.raises(UnsupportedEvaluatorVersion):
        excluded(
            meta, OracleSpec(), "infrastructure_failure", "test", experimental_evaluator="1.7.0"
        )


def test_empty_explicit_experiment_has_zero_configured_and_no_measured_outcomes():
    summary = experimental_summary([], evaluator_version="1.4.0")
    assert summary["configured_trials"] == 0
    coverage = summary["attack_outcome_coverage"]
    assert coverage["configured_attack_trials"] == 0
    assert coverage["coverage"]["value"] is None
    assert coverage["attack_success"]["denominator"] == 0


@pytest.mark.parametrize("config", [None, [], "malformed"])
def test_malformed_context_shape_returns_typed_error_with_requested_version(config):
    scenario, evidence, meta = case()
    evidence.execution["config"] = config
    result = score(scenario, OracleSpec(), evidence, meta, experimental_evaluator="1.4.0")
    assert result.evaluator_version == "1.4.0" and result.status == "evidence_error"
    assert result.scoring_provenance["effective_evaluator_version"] is None
    assert result.experimental["context_error"] == "experimental_context_conflict"
    assert result.experimental["planned_trial"]["status"] == "unavailable"


def result_with_plan(kind):
    _, _, meta = case()
    result = excluded(
        meta, OracleSpec(), "infrastructure_failure", "test", experimental_evaluator="1.4.0"
    )
    plan = (
        unavailable_plan()
        if kind == "missing"
        else plan_for(None, "frozen_manifest", "hash", configured=kind != "empty")
    )
    if kind not in {"missing", "empty"}:
        plan["attack_count"] = 1
    attach_plan(result, plan)
    result.experimental["verified_attack_exposure"] = {
        "known": True,
        "unknown": True,
        "unexposed": False,
    }.get(kind)
    if kind == "known":
        result.eligible = True
        result.status = "successful"
        result.attack_eligible = True
        result.scoring_provenance.update(
            effective_evaluator_version="1.4.0",
            result_classification="scored",
            error_classification=None,
        )
        result.attacker_success = True
    return result


@pytest.mark.parametrize(
    "kind,configured,unknown,unexposed,determinate",
    [
        ("known", 1, 0, 0, 1),
        ("unknown", 1, 1, 0, 0),
        ("early_error", 1, 1, 0, 0),
        ("unexposed", 1, 0, 1, 0),
        ("empty", 0, 0, 0, 0),
        ("missing", None, 0, 0, 0),
    ],
)
def test_planned_coverage_distinguishes_missing_unknown_and_unexposed(
    kind, configured, unknown, unexposed, determinate
):
    summary = experimental_summary([result_with_plan(kind)])
    c = summary["attack_outcome_coverage"]
    assert summary["configured_trials"] == configured
    assert c["unknown_trials"] == unknown and c["unexposed_controls"] == unexposed
    assert c["determinate_trials"] == determinate
    assert c["measured_failures"] == 0
    if kind == "early_error":
        assert c["coverage"]["value"] == 0 and c["coverage"]["denominator"] == 1
    if kind == "missing":
        assert c["coverage"]["denominator"] is None


@pytest.mark.parametrize(
    "kind", ["early_error", "missing", "unknown", "unexposed", "known", "empty"]
)
def test_json_csv_markdown_have_identical_coverage_and_frozen_reporting_is_repeatable(
    tmp_path, kind
):
    from agent_reliability_lab.evaluation.metrics import summarize

    result = result_with_plan(kind)
    summary = summarize([result])
    summary.update(security=experimental_summary([result]), per_scenario={})
    document = dict(
        experiment_id="synthetic",
        report_id="first",
        manifest={"purpose": "scripted_infrastructure_validation"},
        summary=summary,
        results=[result.model_dump(mode="json")],
    )
    initial = copy.deepcopy(document)
    first = export(document, tmp_path)
    document["report_id"] = "second"
    second = export(document, tmp_path)
    rows = {
        r["metric"]: r
        for r in csv.DictReader((first / "metrics.csv").open())
        if r["scenario_id"] == "__security__"
    }
    for key in ("configured_trials", "unknown_trials", "measured_failures", "determinate_trials"):
        expected = summary["security"].get(
            key, summary["security"]["attack_outcome_coverage"].get(key)
        )
        if expected is None:
            assert rows[key]["value"] == "" and rows[key]["status"] == "unavailable"
        else:
            assert int(rows[key]["value"]) == expected
    configured = json.dumps(summary["security"]["configured_trials"])
    assert f'"configured_trials": {configured}' in (first / "report.md").read_text()
    assert json.loads((first / "results.json").read_text())["summary"] == summary
    assert (first / "metrics.csv").read_bytes() == (second / "metrics.csv").read_bytes()
    document["report_id"] = "first"
    assert document == initial
