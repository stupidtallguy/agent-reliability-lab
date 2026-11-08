import uuid

import pytest

from agent_reliability_lab.agent.config import AgentConfig, ModelConfig
from agent_reliability_lab.agent.execution import AgentExecution
from agent_reliability_lab.opsdesk.database import SandboxManager, engine_from_env
from agent_reliability_lab.opsdesk.fixtures import baseline_access, load_baseline


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def agent_env():
    engine = engine_from_env()
    manager = SandboxManager(engine)
    manager.initialize()
    created = []

    def provision(access=None):
        run_id = "agent_test_" + uuid.uuid4().hex[:20]
        sandbox = manager.provision(run_id, load_baseline(), access or baseline_access())
        created.append(run_id)
        return sandbox

    sandbox = provision()
    host = AgentExecution(engine)

    def configuration(script, **settings):
        return AgentConfig(
            sandbox_run_id=sandbox.run_id,
            actor_id=settings.pop("actor_id", "support_001"),
            tenant_id="opsdesk",
            transport=settings.pop("transport", "memory"),
            model=ModelConfig(script=script, repeat_last=settings.pop("repeat_last", False)),
            **settings,
        )

    yield host, sandbox, configuration, provision
    for run_id in reversed(created):
        manager.cleanup(run_id)
    engine.dispose()
