"""All integration resources are fresh and explicitly owned by this test fixture."""

import json
from pathlib import Path

import pytest

from agent_reliability_lab.evaluation.contracts import ExperimentConfig
from agent_reliability_lab.evaluation.runner import ScenarioRunner
from agent_reliability_lab.opsdesk.database import engine_from_env

ROOT = Path(__file__).parents[2]


def configuration(**updates):
    payload = json.loads((ROOT / "benchmarks/evaluation/checkpoint5.json").read_text())
    payload.update({"transport": "memory", **updates})
    return ExperimentConfig.model_validate_json(json.dumps(payload))


def path_for(sid):
    for category in ("faults", "attacks", "controls"):
        path = ROOT / f"benchmarks/{category}/development/{sid}.json"
        if path.exists():
            return path
    return ROOT / f"benchmarks/development/{sid}.json"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def lab():
    engine = engine_from_env()
    runner = ScenarioRunner(engine)
    experiments = []

    async def run(sids, config=None, **kwargs):
        identifier = await runner.run(
            [path_for(sid) for sid in sids], config or configuration(), **kwargs
        )
        experiments.append(identifier)
        pairs = [
            (trial, runner.store.scores(trial["trial_id"])[-1])
            for trial in runner.store.list_trials(experiment_id=identifier)
        ]
        return identifier, pairs

    yield runner, run
    for identifier in experiments:
        for trial in runner.store.list_trials(experiment_id=identifier):
            if trial["sandbox_run_id"] and trial["cleanup"]["status"] != "cleaned":
                # Only test-owned executions, after the test has explicitly stopped.
                runner.manager.cleanup(
                    trial["sandbox_run_id"], expected_marker=trial["ownership_marker"]
                )
    engine.dispose()
