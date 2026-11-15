import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import schedule, starter_draft
from agent_reliability_lab.research.benchmark_contracts import (
    BenchmarkCase,
    BenchmarkDataset,
    BenchmarkProtocol,
    StatisticalPlan,
)
from agent_reliability_lab.research.benchmark_measurements import (
    MEASUREMENTS,
    observation,
    summarize_pairs,
    trial_measurements,
)
from agent_reliability_lab.research.contracts import parse_artifact


@pytest.fixture
def bundle():
    return starter_draft(repetitions=2, order_seed=19)


def rebind_case(original, new_identity, *, partition="held_out", same_stimulus=False):
    raw = original.model_dump(mode="json")
    scenario = raw["case"]["scenario"]
    scenario["scenario_id"] = new_identity
    scenario["metadata"]["split"] = "held_out" if partition == "held_out" else "development"
    if not same_stimulus:
        scenario["user_request"] += " Confirm the order number."
    raw["partition"] = partition
    from agent_reliability_lab.benchmarks.scenario import Scenario

    canonical = Scenario.model_validate(scenario).model_dump(mode="json")
    raw["case"]["oracle"]["scenario_hash"] = raw["harness"]["scenario_hash"] = digest(canonical)
    for injection in [*raw["harness"]["attacks"], *raw["harness"]["faults"]]:
        injection["scenario_id"] = new_identity
    return BenchmarkCase.model_validate(raw)


@pytest.mark.parametrize("kind", ["template", "template_family", "attack_family", "attack_payload"])
@pytest.mark.parametrize("partition", ["training", "held_out"])
def test_dataset_rejects_cross_partition_leakage(bundle, kind, partition):
    dataset, _ = bundle
    original = next(c for c in dataset.cases if c.harness.attacks)
    clone = rebind_case(original, "independent_candidate", partition=partition)
    payload = clone.model_dump(mode="json")
    if kind != "template":
        payload["template_id"] = "other_template"
    if kind in {"attack_family", "attack_payload"}:
        payload["template_family"] = "other_template_family"
    if kind == "attack_family":
        attack = payload["harness"]["attacks"][0]
        attack["payload"] += " Confirm the manager's name."
        attack["payload_hash"] = hashlib.sha256(attack["payload"].encode()).hexdigest()
    if kind == "attack_payload":
        payload["attack_family"] = "other_attack_family"
    with pytest.raises(ValidationError, match=kind + " crosses benchmark partitions"):
        BenchmarkDataset.model_validate_json(
            json.dumps(
                {
                    **dataset.model_dump(mode="json"),
                    "cases": [original.model_dump(mode="json"), payload],
                }
            )
        )


def test_dataset_rejects_duplicate_executable_input_even_when_relabelled(bundle):
    dataset, _ = bundle
    original = next(c for c in dataset.cases if not c.harness.attacks)
    renamed = rebind_case(original, "alias_scenario", same_stimulus=True).model_copy(
        update={"template_id": "alias_template", "template_family": "alias_family"}
    )
    with pytest.raises(ValidationError, match="duplicate scenario"):
        BenchmarkDataset.model_validate(
            {
                **dataset.model_dump(),
                "cases": [original, renamed],
            }
        )


def test_disjoint_training_and_held_out_catalog_is_valid_but_not_executable(bundle):
    dataset, protocol = bundle
    payload = dataset.model_dump(mode="json")
    clone = rebind_case(dataset.cases[0], "held_out_example").model_dump(mode="json")
    clone.update(template_id="held_out_template", template_family="held_out_group")
    training = rebind_case(dataset.cases[1], "training_example", partition="training")
    training = training.model_dump(mode="json")
    training.update(template_id="training_template", template_family="training_group")
    payload["cases"] += [clone, training]
    valid = BenchmarkDataset.model_validate_json(json.dumps(payload))
    assert {case.partition for case in valid.cases} == {"training", "development", "held_out"}
    with pytest.raises(ValueError, match="frozen development scenario"):
        schedule(valid, protocol.model_copy(update={"scenarios": ["held_out_example"]}))


def test_dataset_and_protocol_versions_and_schedule(bundle):
    dataset, protocol = bundle
    assert parse_artifact(dataset.model_dump(mode="json")) == dataset
    assert parse_artifact(protocol.model_dump(mode="json")) == protocol
    slots, _ = schedule(dataset, protocol)
    assert schedule(dataset, protocol)[0] == slots
    assert len(slots) == protocol.planned_pairs == 16
    for first, second in zip(slots[::2], slots[1::2], strict=True):
        assert first["slot"] != second["slot"]
        assert first["order"][::-1] == second["order"]
        assert first["fixture_seed"] == second["fixture_seed"]
    data = dataset.model_dump(mode="json")
    data["cases"][0]["benchmark_version"] = "9.9.9"
    with pytest.raises(ValidationError, match="inconsistent benchmark version"):
        BenchmarkDataset.model_validate_json(json.dumps(data))


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"version": 2}, "immediate predecessor"),
        ({"planned_pairs": 1}, "pair count"),
        ({"model": {"provider": "openai", "model_id": "explicit-live"}}, "scripted model"),
    ],
)
def test_preregistration_fails_closed(bundle, overrides, reason):
    _, protocol = bundle
    with pytest.raises(ValidationError, match=reason):
        BenchmarkProtocol.model_validate_json(
            json.dumps({**protocol.model_dump(mode="json"), **overrides})
        )


def test_cluster_estimate_preserves_unknowns_and_weighting():
    def row(cluster, a, b, comparison="verified"):
        return dict(
            template_family=cluster,
            comparison=comparison,
            arms={
                "baseline": {"measurements": dict.fromkeys(MEASUREMENTS, a)},
                "guarded": {"measurements": dict.fromkeys(MEASUREMENTS, b)},
            },
        )

    rows = [
        row("aa", observation(False), observation(True)),
        row("aa", observation(False), observation(True)),
        row("aa", observation(False), observation(True)),
        row("bb", observation(True), observation(False)),
        row("cc", observation(status="contradictory"), observation(True)),
        row("dd", observation(status="not_applicable"), observation(status="not_applicable")),
        row("ee", observation(True), observation(True), comparison="excluded"),
    ]
    plan = StatisticalPlan(bootstrap_seed=44)
    result = summarize_pairs(rows, plan)["task_success"]
    assert result["complete_pairs"] == 4
    assert result["baseline_rate"] == {"numerator": 1, "denominator": 4}
    assert result["guarded_rate"] == {"numerator": 3, "denominator": 4}
    assert result["paired_mean_difference"] == 0.5
    assert result["equal_cluster_mean_difference"] == 0
    assert result["interval_95"] == [-1, 1]
    assert result["template_clusters"] == 2
    assert result["not_applicable_pairs"] == 1 and result["unresolved_or_excluded_pairs"] == 2
    assert result["arm_status_counts"]["baseline"]["contradictory"] == 1
    assert result["sensitivity_bounds"] == [0, 2 / 3]
    assert result["relative_change"] is None
    assert result == summarize_pairs(rows, plan)["task_success"]


def test_independent_outcomes_distinguish_unknown_failure_and_duplicate_audits(bundle):
    dataset, _ = bundle
    item = next(c for c in dataset.cases if c.scenario_id == "fault_lost_create")
    result = SimpleNamespace(
        eligible=True,
        objective_success=False,
        status="incorrect_final_state",
        reconciliation={"complete": True, "errors": []},
        unauthorized_attempt=None,
        unsafe=False,
        recovered=None,
        recovery_eligible=False,
        duration_seconds=None,
        timing_complete=False,
        tool_attempts=2,
        usage={},
        cost={},
        mode="scripted",
    )
    audit = dict(
        operation="create_task",
        before=None,
        after=dict(title="Shipment follow-up", customer_id="customer_001"),
        actor_id=item.case.scenario.actor.actor_id,
        tenant_id=item.case.scenario.actor.tenant_id,
    )
    evidence = dict(audits=[audit], execution={})
    values = trial_measurements(item, result, evidence)
    assert values["task_success"]["status"] == "verified_failure"
    assert values["unauthorized_attempt"]["status"] == "unresolved"
    assert values["duplicate_effect"]["value"] is False
    assert values["model_tokens"]["value"] is None
    assert (
        trial_measurements(item, result, {**evidence, "audits": [audit, audit]})[
            "duplicate_effect"
        ]["value"]
        is True
    )
    result.reconciliation = {"complete": False, "errors": [dict(code="receipt_response_conflict")]}
    assert (
        trial_measurements(item, result, evidence)["duplicate_effect"]["status"] == "contradictory"
    )
    assert trial_measurements(item, None, evidence)["task_success"]["status"] == "unavailable"


def test_false_refusal_requires_a_completed_matching_response_and_failed_task(bundle):
    dataset, _ = bundle
    item = next(c for c in dataset.cases if c.scenario_id == "benign_technical_words")
    result = SimpleNamespace(
        eligible=True,
        objective_success=False,
        reconciliation={"complete": True, "errors": []},
        unauthorized_attempt=False,
        unsafe=False,
        duration_seconds=None,
        timing_complete=False,
        tool_attempts=1,
        usage={},
        cost={},
        mode="scripted",
    )
    terminal = {"answer": "I cannot comply.", "response_completed": True}
    evidence = {"execution": {"result": terminal}}
    assert trial_measurements(item, result, evidence)["false_refusal"]["value"] is True
    result.objective_success = True
    assert trial_measurements(item, result, evidence)["false_refusal"]["value"] is False
    terminal["response_completed"] = False
    assert trial_measurements(item, result, evidence)["false_refusal"]["status"] == "unresolved"
