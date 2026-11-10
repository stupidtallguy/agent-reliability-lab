import pytest

from agent_reliability_lab.evaluation.runner import ScenarioRunner
from agent_reliability_lab.opsdesk.database import engine_from_env
from tests.finalization.support import path_for

from .support import configuration


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def lab():
    engine = engine_from_env()
    assert engine.url.database in {"opsdesk_lab_test", "opsdesk_lab_ci"}, (
        "Corrective tests require an isolated test database, never the protected research DB."
    )
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
        for trial in runner.store.list_trials(experiment_id=identifier):
            if trial["sandbox_run_id"] and trial["cleanup"]["status"] != "cleaned":
                assert trial["sandbox_run_id"].startswith("eval_") and trial["ownership_marker"]
                runner.manager.cleanup(
                    trial["sandbox_run_id"], expected_marker=trial["ownership_marker"]
                )
    engine.dispose()
