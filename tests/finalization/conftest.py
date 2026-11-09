import pytest

from agent_reliability_lab.evaluation.runner import ScenarioRunner
from agent_reliability_lab.opsdesk.database import engine_from_env

from .support import configuration, path_for


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def lab():
    engine = engine_from_env()
    runner = ScenarioRunner(engine)
    owned = []

    async def run(sids, config=None, **kwargs):
        identifier = await runner.run(
            [path_for(s) for s in sids], config or configuration(), **kwargs
        )
        owned.append(identifier)
        return identifier, [
            (t, runner.store.scores(t["trial_id"])[-1])
            for t in runner.store.list_trials(experiment_id=identifier)
        ]

    yield runner, run
    for identifier in owned:
        for t in runner.store.list_trials(experiment_id=identifier):
            if t["sandbox_run_id"] and t["cleanup"]["status"] != "cleaned":
                assert t["sandbox_run_id"].startswith("eval_") and t["ownership_marker"]
                runner.manager.cleanup(t["sandbox_run_id"], expected_marker=t["ownership_marker"])
    engine.dispose()
