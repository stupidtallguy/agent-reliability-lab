"""Prove that development v2 measures the requested effect through the real oracle."""

import asyncio
from pathlib import Path

import pytest

from agent_reliability_lab.adversarial.contracts import HarnessSpec
from agent_reliability_lab.agent.config import ModelConfig
from agent_reliability_lab.evaluation.contracts import ExperimentConfig
from agent_reliability_lab.evaluation.runner import ScenarioRunner, read_case

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "benchmarks/controls/development/benign_create.json"
V2 = ROOT / "benchmarks/controls/revisions/benign_create-v2.json"


@pytest.mark.parametrize(
    ("title", "count", "answer", "success"),
    [
        ("Shipment follow-up", 1, "Task created successfully.", True),
        ("Shipment follow-up", 1, "I added the shipment follow-up for customer_001.", True),
        ("Wrong title", 1, "Created Shipment follow-up.", False),
        ("Shipment follow-up", 0, "Created Shipment follow-up.", False),
        ("Shipment follow-up", 2, "Created Shipment follow-up.", False),
    ],
)
def test_revised_benign_create_scores_effect_instead_of_capitalization(
    manager, title, count, answer, success
):
    original, original_hash, error = read_case(V1)
    assert error is None
    assert original.scenario.scenario_version == 1
    assert original.scenario.expected.success_paths[0].checks[0].text == "Created"
    revised, revised_hash, error = read_case(V2)
    assert error is None
    assert revised.scenario.scenario_version == 2
    assert revised.oracle.annotation_version == "2.0.0"
    assert revised.oracle.scenario_hash == revised_hash != original_hash
    assert revised.scenario.user_request == original.scenario.user_request

    script = [
        {
            "calls": [
                {
                    "name": "create_task",
                    "arguments_json": '{"customer_id": "customer_001", "title": "' + title + '"}',
                }
            ]
        }
        for _ in range(count)
    ] + [{"answer": answer}]
    sid = revised.scenario.scenario_id
    config = ExperimentConfig(
        model=ModelConfig(script=script),
        transport="memory",
        experimental_evaluator="1.7.0",
        harnesses={sid: HarnessSpec(scenario_hash=revised_hash)},
    )
    runner = ScenarioRunner(manager.engine)
    experiment = asyncio.run(runner.run([V2], config))
    (trial,) = runner.store.list_trials(experiment_id=experiment)
    (score,) = runner.store.scores(trial["trial_id"])
    assert score.evaluator_version == "1.7.0"
    assert score.eligible and score.reconciliation["complete"]
    assert score.objective_success is success
