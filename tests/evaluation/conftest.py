from pathlib import Path

import pytest

from agent_reliability_lab.benchmarks.scenario import Scenario
from agent_reliability_lab.evaluation.contracts import Evidence, ExperimentConfig, OracleSpec
from agent_reliability_lab.evaluation.runner import ScenarioRunner
from agent_reliability_lab.opsdesk.database import engine_from_env
from agent_reliability_lab.opsdesk.fixtures import digest

ROOT = Path(__file__).parents[2]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def case_data(name):
    scenario = Scenario.model_validate_json(
        (ROOT / "benchmarks/development" / f"{name}.json").read_text()
    )
    evidence = Evidence.model_validate_json(
        (Path(__file__).parent / "data" / f"{name}.json").read_text()
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
    return scenario, OracleSpec(), evidence, meta


@pytest.fixture
def normal_data():
    return case_data("normal_order_status")


@pytest.fixture
def write_data():
    return case_data("multi_step_resolve_task")


@pytest.fixture
def eval_env():
    engine = engine_from_env()
    runner = ScenarioRunner(engine)
    experiments = []

    async def run(paths=None, config=None, **options):
        paths = paths or [ROOT / "benchmarks/development/normal_order_status.json"]
        config = config or ExperimentConfig(transport="memory")
        experiment_id = await runner.run(paths, config, **options)
        experiments.append(experiment_id)
        return experiment_id

    yield runner, run
    # Only explicitly tracked, test-owned resources; no global schema sweep.
    for experiment_id in experiments:
        for trial in runner.store.list_trials(experiment_id=experiment_id):
            if trial["sandbox_run_id"] and trial["cleanup"]["status"] != "cleaned":
                from agent_reliability_lab.agent.persistence import ExecutionStore

                if trial["execution_id"]:
                    with ExecutionStore(engine).claim(trial["execution_id"]):
                        runner.manager.cleanup(
                            trial["sandbox_run_id"], expected_marker=trial["ownership_marker"]
                        )
                else:
                    runner.manager.cleanup(
                        trial["sandbox_run_id"], expected_marker=trial["ownership_marker"]
                    )
    engine.dispose()
