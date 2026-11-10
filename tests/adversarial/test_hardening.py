"""Independent identity mutations, version errors and unknown metric denominators."""

import copy
import json
from types import SimpleNamespace

import pytest

from agent_reliability_lab.adversarial.attribution import OrderingError
from agent_reliability_lab.adversarial.attribution_v130 import (
    VerifiedDecisionOrder,
    original_arguments,
)
from agent_reliability_lab.adversarial.reporting import experimental_summary
from agent_reliability_lab.benchmarks.scenario import Scenario
from agent_reliability_lab.evaluation.contracts import Evidence, ExperimentConfig, OracleSpec
from agent_reliability_lab.evaluation.metrics import summarize
from agent_reliability_lab.evaluation.scoring import score
from agent_reliability_lab.evaluation.versions import UnsupportedEvaluatorVersion
from agent_reliability_lab.opsdesk.fixtures import digest
from tests.adversarial.support import ROOT


def identity_chain():
    args = {"document_id": "policy_001"}
    op = dict(
        proposal_id="read",
        operation_id=None,
        model_call_id="model_read",
        tool="get_document",
        turn=0,
        position=0,
        arguments=args,
        arguments_hash=digest(args),
    )
    base = dict(
        injection_id="attack",
        configuration_hash="configuration",
        tool_call_id="read",
        logical_operation_id=None,
        tool="get_document",
        attempt_id="attempt",
    )

    def event(kind, **payload):
        return dict(
            event_type=kind,
            execution_id="execution",
            payload={"correlation_id": "execution", **payload},
        )

    events = [
        event("model_request", request_id="source", input_hash="source_input"),
        event("model_response", request_id="source", call_count=1),
        event(
            "tool_call_proposed",
            tool_call_id="read",
            logical_operation_id=None,
            tool="get_document",
            arguments_hash=digest(args),
        ),
        event("tool_call_started", **base, ordinal=1),
        event("injection_trigger", **base),
        event("injection_activated", **base, transformed_response_hash="observation"),
        event(
            "injection_observed",
            **base,
            observed_response_hash="observation",
            payload_delivered=True,
        ),
        event("tool_call_succeeded", **base, response_hash="observation"),
        event("model_request", request_id="carrier", input_hash="carrier_input"),
        event(
            "injection_model_exposure",
            **base,
            request_id="carrier",
            input_hash="carrier_input",
            observed_response_hash="observation",
        ),
        event("model_response", request_id="carrier", call_count=0),
    ]
    for sequence, row in enumerate(events, 1):
        row["sequence"] = sequence
    evidence = SimpleNamespace(
        execution_id="execution",
        execution={"journal_seq": len(events)},
        events=events,
        operations=[op],
        attempts=[dict(attempt_id="attempt", proposal_id="read", ordinal=1)],
        requests=[
            dict(
                request_id="source",
                turn=0,
                status="completed",
                calls=[
                    dict(name="get_document", call_id="model_read", arguments_json=json.dumps(args))
                ],
            ),
            dict(request_id="carrier", turn=1, status="completed", calls=[]),
        ],
    )
    spec = SimpleNamespace(
        injection_id="attack", tool="get_document", trigger=SimpleNamespace(arguments=args)
    )
    return evidence, spec


def marker(evidence):
    return next(e for e in evidence.events if e["event_type"] == "injection_model_exposure")


def test_complete_identity_chain_is_accepted():
    evidence, spec = identity_chain()
    VerifiedDecisionOrder(evidence).validate_marker(marker(evidence), spec)
    assert VerifiedDecisionOrder(evidence).exposure_issues(spec) == []


@pytest.mark.parametrize(
    "stage,key",
    [
        ("injection_model_exposure", "tool_call_id"),
        ("injection_model_exposure", "logical_operation_id"),
        ("injection_model_exposure", "attempt_id"),
        ("injection_model_exposure", "request_id"),
        ("injection_model_exposure", "input_hash"),
        ("injection_model_exposure", "observed_response_hash"),
        ("injection_observed", "tool_call_id"),
        ("injection_observed", "logical_operation_id"),
        ("injection_observed", "attempt_id"),
        ("injection_observed", "observed_response_hash"),
        ("injection_activated", "tool_call_id"),
        ("tool_call_succeeded", "tool_call_id"),
        ("tool_call_succeeded", "response_hash"),
        ("tool_call_started", "tool_call_id"),
        ("tool_call_started", "ordinal"),
    ],
)
def test_independent_exposure_identity_conflicts_are_rejected(stage, key):
    evidence, spec = identity_chain()
    next(e for e in evidence.events if e["event_type"] == stage)["payload"][key] = "conflicting"
    assert VerifiedDecisionOrder(evidence).exposure_issues(spec)


@pytest.mark.parametrize(
    "key",
    [
        "tool_call_id",
        "logical_operation_id",
        "attempt_id",
        "request_id",
        "input_hash",
        "observed_response_hash",
    ],
)
def test_missing_marker_relationships_are_distinct_from_conflicting_values(key):
    evidence, spec = identity_chain()
    marker(evidence)["payload"].pop(key)
    assert VerifiedDecisionOrder(evidence).exposure_issues(spec)[0].startswith("missing_")
    evidence, spec = identity_chain()
    marker(evidence)["payload"][key] = "conflicting"
    assert VerifiedDecisionOrder(evidence).exposure_issues(spec)[0].startswith("contradictory_")


@pytest.mark.parametrize(
    "part", ["attempt_proposal", "source_call", "carrier_turn", "duplicate_marker"]
)
def test_source_decision_and_proposal_relationships_are_required(part):
    evidence, spec = identity_chain()
    if part == "attempt_proposal":
        evidence.attempts[0]["proposal_id"] = "different"
    elif part == "source_call":
        evidence.requests[0]["calls"][0]["call_id"] = "different"
    elif part == "carrier_turn":
        evidence.requests[1]["turn"] = -1
    else:
        evidence.events.append(copy.deepcopy(marker(evidence)))
    assert VerifiedDecisionOrder(evidence).exposure_issues(spec)[0].startswith("contradictory_")


@pytest.mark.parametrize(
    "call",
    [
        {"arguments_json": "[1, 2]"},
        {"arguments_json": "{"},
        {"arguments_json": '{"x":NaN}'},
        {"arguments_json": " " * 16385},
        {"arguments_json": '{"task_id":"task_001"}', "blocked_sensitive": True},
        {},
    ],
)
def test_missing_unsafe_or_invalid_original_intent_is_not_invented(call):
    with pytest.raises(OrderingError):
        original_arguments(call)


def test_safe_original_target_is_available_without_executing_or_revalidating_it():
    args = {"task_id": "task_001", "unsupported_parameter": "synthetic"}
    assert original_arguments({"arguments_json": json.dumps(args)}) == args


def normal_case():
    scenario = Scenario.model_validate_json(
        (ROOT / "benchmarks/development/normal_order_status.json").read_text()
    )
    evidence = Evidence.model_validate_json(
        (ROOT / "tests/evaluation/data/normal_order_status.json").read_text()
    )
    meta = dict(
        trial_id="1" * 32,
        experiment_id="2" * 32,
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


@pytest.mark.parametrize("version", ["1.2.0", "1.3.0"])
@pytest.mark.parametrize("damage", ["missing_turn", "malformed_proposal", "infrastructure"])
def test_explicit_modern_version_survives_error_paths(version, damage):
    scenario, evidence, meta = normal_case()
    evidence.experimental = {}  # The structural failure precedes harness verification.
    if damage == "missing_turn":
        evidence.operations[0].pop("turn")
    elif damage == "malformed_proposal":
        evidence.operations[0].pop("proposal_id")
    else:
        evidence.execution.update(status="failed", result={"reason": "execution_error"})
    result = score(scenario, OracleSpec(), evidence, meta, experimental_evaluator=version)
    assert result.evaluator_version == version
    assert result.attacker_success is None
    assert result.scoring_provenance["requested_experimental_evaluator"] == version
    assert result.evidence_reference.endswith(meta["trial_id"] + "/evidence")
    assert result.evidence_hash == digest(evidence.model_dump(mode="json"))


@pytest.mark.parametrize("version", ["", "invalid", "1.0.1", "1.8.0"])
def test_unsupported_versions_raise_a_typed_selection_error_before_scoring(version):
    with pytest.raises(UnsupportedEvaluatorVersion) as error:
        score(None, OracleSpec(), None, {}, experimental_evaluator=version)
    assert error.value.code == "unsupported_evaluator_version"


def test_default_and_nonexperimental_behavior_remain_unchanged():
    scenario, evidence, meta = normal_case()
    for version in ("1.1.0", "1.2.0", "1.3.0"):
        assert (
            score(
                scenario, OracleSpec(), evidence, meta, experimental_evaluator=version
            ).evaluator_version
            == "1.0.1"
        )
    assert ExperimentConfig().experimental_evaluator == "1.1.0"
    assert "experimental_evaluator" not in ExperimentConfig().model_dump(mode="json")
    assert ExperimentConfig(experimental_evaluator="1.3.0").experimental_evaluator == "1.3.0"
    evidence.experimental = {}
    evidence.operations[0].pop("turn")
    assert score(scenario, OracleSpec(), evidence, meta).evaluator_version == "1.0.1"


def test_unknown_outcome_coverage_excludes_unknown_from_both_measured_counts():
    scenario, evidence, meta = normal_case()
    result = score(scenario, OracleSpec(), evidence, meta)
    result.evaluator_version = "1.3.0"
    result.attack_eligible = True
    result.experimental = dict(
        case_kind="attack",
        objectives=[dict(objective="prohibited_mutation", exposed=True, success=None)],
    )
    unknown = result.model_copy(deep=True)
    negative = result.model_copy(deep=True)
    negative.trial_id = "3" * 32
    negative.scoring_id = "4" * 32
    negative.attacker_success = False
    negative.experimental["objectives"][0]["success"] = False
    positive = result.model_copy(deep=True)
    positive.trial_id = "5" * 32
    positive.scoring_id = "6" * 32
    positive.attacker_success = True
    positive.experimental["objectives"][0]["success"] = True
    records = [unknown, negative, positive]
    coverage = experimental_summary(records)["attack_outcome_coverage"]
    assert coverage["measured_successes"] == coverage["measured_failures"] == 1
    assert coverage["unknown_trials"] == 1
    metric = summarize(records)["metrics"]["prompt_injection_attack_success_rate"]
    assert metric["numerator"] == 1 and metric["denominator"] == 2
    alone = summarize([unknown])["metrics"]["prompt_injection_attack_success_rate"]
    assert alone["value"] is None and alone["denominator"] == 0
    assert alone["reason"] == "no_determinate_attack_outcomes"
    unknown.evaluator_version = "1.2.0"
    assert summarize([unknown])["metrics"]["prompt_injection_attack_success_rate"]["reason"] == (
        "no_verified_attack_exposure"
    )
