"""Real PostgreSQL only: absent/unreachable configuration fails, never skips."""

import uuid

import pytest
import sqlalchemy as sa

from agent_reliability_lab.opsdesk import tables as t
from agent_reliability_lab.opsdesk.database import SandboxManager, engine_from_env
from agent_reliability_lab.opsdesk.fixtures import baseline_access, load_baseline


@pytest.fixture(scope="session")
def manager():
    engine = engine_from_env()
    manager = SandboxManager(engine)
    manager.initialize()
    yield manager
    engine.dispose()


@pytest.fixture
def sandbox_factory(manager):
    created = []

    def factory(seed=None, access=None):
        run_id = "test_" + uuid.uuid4().hex[:20]
        sandbox = manager.provision(run_id, seed or load_baseline(), access or baseline_access())
        created.append(run_id)
        return sandbox

    yield factory
    for run_id in reversed(created):
        with manager.engine.connect() as connection:
            exists = connection.execute(
                sa.select(t.registry.c.run_id).where(t.registry.c.run_id == run_id)
            ).first()
        if exists:
            manager.cleanup(run_id)


@pytest.fixture
def sandbox(sandbox_factory):
    return sandbox_factory()
