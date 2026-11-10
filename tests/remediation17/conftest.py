import os
import uuid

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
    assert os.environ.get("OPSDESK_TEST_OWNED") == "1"
    assert engine.url.database in {"opsdesk_lab_test", "opsdesk_lab_ci"}
    assert engine.url.port not in {55432, 55433}, "Never mutate protected or previous test evidence"
    runner = ScenarioRunner(engine)
    owned = []

    async def run(sid="attack_hijack", config=None, **options):
        identifier = await runner.run([path_for(sid)], config or configuration(), **options)
        owned.append(identifier)
        trial = runner.store.list_trials(experiment_id=identifier)[0]
        return trial, runner.store.scores(trial["trial_id"])[-1]

    yield runner, run
    for identifier in owned:
        for t in runner.store.list_trials(experiment_id=identifier):
            if t["sandbox_run_id"] and t["cleanup"]["status"] != "cleaned":
                runner.manager.cleanup(t["sandbox_run_id"], expected_marker=t["ownership_marker"])
    engine.dispose()


@pytest.fixture
def scope():
    return "test_" + uuid.uuid4().hex
