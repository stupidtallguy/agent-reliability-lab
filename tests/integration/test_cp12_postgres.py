import copy
import uuid

import pytest

from agent_reliability_lab.evaluation.tables import trials
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import (
    execute_benchmark,
    schedule,
    starter_draft,
    verify_result,
)
from agent_reliability_lab.research.contracts import parse_artifact
from agent_reliability_lab.research.persistence import ResearchStore

pytestmark = pytest.mark.integration


@pytest.mark.anyio
async def test_cp12_frozen_pairs_scores_and_tamper_detection(manager, monkeypatch):
    monkeypatch.setenv("OPSDESK_TEST_OWNED", "1")
    store = ResearchStore(manager.engine, "test_cp12_" + uuid.uuid4().hex)
    await store.initialize()
    dataset, plan = starter_draft(repetitions=1)
    selected = [
        "multi_step_resolve_task",
        "authorization_viewer_update",
        "attack_hijack",
        "fault_lost_create",
    ]
    plan = plan.model_copy(
        update={
            "scenarios": selected,
            "planned_pairs": len(selected),
            "scripts": {scenario: plan.scripts[scenario] for scenario in selected},
        }
    )
    store.append(dataset)
    registered = store.append(plan)
    with pytest.raises(ValueError, match="consecutively"):
        store.append(plan.model_copy(update={"order_seed": 9}))
    amendment = store.append(
        plan.model_copy(
            update={
                "version": 2,
                "supersedes": registered,
                "order_seed": 9,
            }
        )
    )
    assert store.get(registered).order_seed != store.get(amendment).order_seed
    assert store.get(registered) == plan

    frozen, artifact = await execute_benchmark(store, registered)
    persisted = store.get(frozen)
    report = verify_result(store, persisted)
    assert persisted == artifact and report == artifact.result
    assert report["started_trials"] == 8 and report["planned_pairs"] == 4
    assert report["partition_counts"] == {"training": 0, "development": 8, "held_out": 0}
    assert [row["order"] for row in report["pairs"]] == [
        slot["order"] for slot in schedule(dataset, plan)[0]
    ]
    assert all(row["comparison"] == "verified" for row in report["pairs"])
    arms = [arm for row in report["pairs"] for arm in row["arms"].values()]
    assert len({arm["execution_id"] for arm in arms}) == len(arms)
    assert len({arm["sandbox_run_id"] for arm in arms}) == len(arms)
    assert all(arm["score_revision"] == 1 and arm["evidence_hash"] for arm in arms)
    refusal = report["pairs"][1]["arms"]
    assert [arm["measurements"]["correct_refusal"]["value"] for arm in refusal.values()] == [
        True,
        True,
    ]
    attack = report["pairs"][2]["arms"]
    assert attack["baseline"]["measurements"]["attack_success"]["value"] is True
    assert attack["guarded"]["measurements"]["attack_success"]["value"] is False

    retried = report["pairs"][-1]
    for arm in retried["arms"].values():
        evidence = store.evaluations.trial(arm["trial_id"])["evidence"]
        assert len(evidence["receipts"]) == len(evidence["audits"]) == 1
        assert arm["measurements"]["tool_attempts"]["value"] == 2
        assert arm["measurements"]["duplicate_effect"]["value"] is False
        assert arm["measurements"]["model_tokens"]["value"] is None

    fabricated = copy.deepcopy(report)
    fabricated["summary"]["task_success"]["complete_pairs"] = 99
    forged = parse_artifact(
        {
            **persisted.model_dump(mode="json"),
            "result": fabricated,
            "result_hash": digest(fabricated),
        }
    )
    with pytest.raises(ValueError, match="does not reproduce"):
        verify_result(store, forged)

    keys = list(persisted.evaluator_reports)
    swapped = dict(persisted.evaluator_reports)
    swapped[keys[0]], swapped[keys[1]] = swapped[keys[1]], swapped[keys[0]]
    with pytest.raises(ValueError, match="incompatible"):
        verify_result(store, persisted.model_copy(update={"evaluator_reports": swapped}))

    victim = report["pairs"][-1]["arms"]["baseline"]["trial_id"]
    original = store.evaluations.trial(victim)["evidence"]
    changed = copy.deepcopy(original)
    changed["audits"][0]["task_id"] = "unrelated_task"
    with manager.engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE opsdesk_evaluation.trials DISABLE TRIGGER immutable_capture"
        )
        connection.execute(
            trials.update()
            .where(trials.c.trial_id == victim)
            .values(evidence=changed, evidence_hash=digest(changed))
        )
        connection.exec_driver_sql(
            "ALTER TABLE opsdesk_evaluation.trials ENABLE TRIGGER immutable_capture"
        )
    with pytest.raises(ValueError, match="score does not pin"):
        verify_result(store, persisted)


@pytest.mark.anyio
async def test_cp12_enforces_shared_runtime_budget(manager, monkeypatch):
    monkeypatch.setenv("OPSDESK_TEST_OWNED", "1")
    store = ResearchStore(manager.engine, "test_cp12_" + uuid.uuid4().hex)
    await store.initialize()
    dataset, plan = starter_draft(repetitions=1)
    scenario = "multi_step_resolve_task"
    plan = plan.model_copy(
        update={
            "scenarios": [scenario],
            "planned_pairs": 1,
            "scripts": {scenario: plan.scripts[scenario]},
            "budgets": plan.budgets.model_copy(update={"max_tool_calls": 1}),
        }
    )
    store.append(dataset)
    _, result = await execute_benchmark(store, store.append(plan))
    for arm in result.result["pairs"][0]["arms"].values():
        trial = store.evaluations.trial(arm["trial_id"])
        assert len(trial["evidence"]["attempts"]) == 1
        assert trial["evidence"]["execution"]["status"] == "budget_exhausted"
        assert arm["measurements"]["task_success"]["value"] is False
