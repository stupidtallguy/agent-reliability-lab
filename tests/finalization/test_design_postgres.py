import json
import uuid
from pathlib import Path

import pytest

from agent_reliability_lab.evaluation.contracts import ExperimentConfig
from agent_reliability_lab.research.contracts import Amendment, Pair, Preregistration, SplitManifest
from agent_reliability_lab.research.pairing import verify_pair
from agent_reliability_lab.research.persistence import ResearchStore

from .research_support import common, oracle
from .support import path_for

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def design(runner):
    store = ResearchStore(runner.engine, "test_" + uuid.uuid4().hex)
    await store.initialize()
    split = SplitManifest.model_validate_json(
        (Path(__file__).parents[2] / "benchmarks/research/split-development.json").read_text()
    )
    splitref = store.append(split)
    scenario = json.loads(path_for("normal_order_status").read_text())
    from agent_reliability_lab.benchmarks.scenario import Scenario
    from agent_reliability_lab.opsdesk.fixtures import digest

    o = oracle()
    o.scenario_id = "normal_order_status"
    o.scenario_hash = digest(
        Scenario.model_validate_json(json.dumps(scenario)).model_dump(mode="json")
    )
    ref = store.append(o)
    return store, splitref, ref


async def test_pairing_pins_actual_frozen_trials_and_oracle(lab, monkeypatch):
    runner, _ = lab
    store, _, ref = await design(runner)
    pairid = uuid.uuid4().hex
    config = ExperimentConfig(transport="memory", pairing_id=pairid)
    # Use the fixture's runner so resource ownership and cleanup remain centralized.
    run = lab[1]
    _, [(baseline, _)] = await run(["normal_order_status"], config)
    _, [(guarded, _)] = await run(
        ["normal_order_status"], config.model_copy(update={"defense": "guarded"})
    )
    verified, criteria, reason = verify_pair(
        runner.store, baseline["trial_id"], guarded["trial_id"], ref
    )
    assert verified == "verified", (criteria, reason)
    pair = Pair(
        **common("synthetic_pair"),
        pair_group="synthetic_group",
        baseline_trial_id=baseline["trial_id"],
        guarded_trial_id=guarded["trial_id"],
        oracle=ref,
        criteria=criteria,
        verification=verified,
        exclusion_reason=reason,
    )
    pinned = store.append(pair)
    assert store.get(pinned).criteria["initial_hash"] is True
    from agent_reliability_lab.research.analysis import analyze
    from agent_reliability_lab.research.views import ResearchView

    split_ref = store.reference(
        SplitManifest.model_validate_json(json.dumps(store.list("split")[0]["body"]))
    )
    summary = analyze(store, [pinned], split_ref, "1.0.1")
    assert summary["summary"]["complete_verified_pairs"] == 1
    assert summary["summary"]["exact_mcnemar_p"] is None
    assert len(summary["selected_scores"]) == 2
    from agent_reliability_lab.evaluation.selection import IncompatibleCohort

    original_scores = store.evaluations.scores

    def incompatible_scores(trial_id):
        results = original_scores(trial_id)
        results[-1].scoring_provenance["adversarial_source_hash"] = (
            "a" * 64 if trial_id == baseline["trial_id"] else "b" * 64
        )
        return results

    with monkeypatch.context() as patch:
        patch.setattr(store.evaluations, "scores", incompatible_scores)
        with pytest.raises(IncompatibleCohort, match="implementation hashes differ"):
            analyze(store, [pinned], split_ref, "1.0.1")
    view = ResearchView(store.engine)
    assert len(view.rows("artifacts", identifier=store.scope, kind="pair")) == 1
    with pytest.raises(ValueError):
        view.rows("arbitrary_sql")
    assert verify_pair(runner.store, baseline["trial_id"], None, ref)[0] == "incomplete"
    assert (
        verify_pair(runner.store, guarded["trial_id"], baseline["trial_id"], ref)[0] == "excluded"
    )


async def test_preregistration_freeze_amendment_and_execution_gate(lab):
    runner, run = lab
    store, splitref, ref = await design(runner)
    config = ExperimentConfig(transport="memory")
    study = Preregistration(
        **common("synthetic_study"),
        mode="exploratory",
        research_question="Can infrastructure reproduce this scripted case?",
        hypotheses=["The frozen order status is reported."],
        primary_outcome="task_success",
        secondary_outcomes=["tool_accuracy"],
        configurations=dict(defense="baseline", transport="memory"),
        model=config.model.model_dump(mode="json"),
        scenario_population=["normal_order_status"],
        categories=["normal"],
        sample_size=1,
        trial_allocation={"normal_order_status": 1},
        pairing_design={"paired": False},
        oracles=[ref],
        evaluator_version="1.1.0",
        split=splitref,
        exclusion_rules=["infrastructure_failure"],
        missing_data_rules=["report_unknown"],
        statistical_plan={"descriptive_only": True},
        interval_method="Wilson_descriptive",
        planned_comparisons=[],
        stopping_rules=["one_trial"],
        budget_limits=config.budgets.model_dump(mode="json"),
    )
    pinned = store.append(study)
    config.study = dict(reference=pinned.model_dump(mode="json"), scope=store.scope)
    _, [(trial, result)] = await run(["normal_order_status"], config)
    assert result.objective_success is True
    proof = runner.store.experiment(trial["experiment_id"])["manifest"]["study_validation"]
    assert proof["reference"] == pinned.model_dump(mode="json")
    assert proof["review_statuses"][0]["status"] == "pending_independent_human_review"
    assert runner.store.experiment(trial["experiment_id"])["manifest"]["config"]["study"][
        "reference"
    ] == pinned.model_dump(mode="json")
    amendment = Amendment(
        **common("synthetic_amendment"),
        preregistration=pinned,
        reason="Synthetic change request.",
        changed_fields={"sample_size": 2},
        confirmatory_impact="requires_new_preregistration",
    )
    store.append(amendment)
    assert store.get(pinned).sample_size == 1
    study.identity = "synthetic_confirmatory"
    study.mode = "confirmatory"
    confirm = store.append(study)
    with pytest.raises(ValueError, match="explicit human/evaluator audit"):
        store.validate_study(confirm, ["normal_order_status"])
    assert not store.list("attestation")
