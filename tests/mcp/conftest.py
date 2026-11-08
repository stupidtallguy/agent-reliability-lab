"""Separate fast protocol mocks and explicitly selected real PostgreSQL fixtures."""

import secrets
import uuid
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from agent_reliability_lab.mcp.context import BoundContext, LaunchConfig
from agent_reliability_lab.opsdesk.database import SandboxManager, engine_from_env
from agent_reliability_lab.opsdesk.fixtures import baseline_access, load_baseline


@pytest.fixture
def anyio_backend():
    return "asyncio"


def configuration(run_id="unit_test", actor_id="support_001", tenant_id="opsdesk") -> LaunchConfig:
    return LaunchConfig(
        run_id=run_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        signing_key=SecretStr(secrets.token_hex(32)),
    )


@pytest.fixture
def mock_binding():
    binding = Mock(spec=BoundContext)
    binding.config = configuration()
    binding.fixture_id = "protocol_unit"
    binding.fixture_version = "1.0"
    binding.seed_hash = "0" * 64
    return binding


@pytest.fixture(scope="session")
def mcp_manager():
    engine = engine_from_env()
    manager = SandboxManager(engine)
    manager.initialize()
    yield manager
    engine.dispose()


@pytest.fixture
def mcp_sandbox_factory(mcp_manager):
    created = []

    def create(seed=None, access=None):
        run_id = "mcp_test_" + uuid.uuid4().hex[:20]
        sandbox = mcp_manager.provision(
            run_id, seed or load_baseline(), access or baseline_access()
        )
        created.append(run_id)
        return sandbox

    yield create
    for run_id in reversed(created):
        mcp_manager.cleanup(run_id)


@pytest.fixture
def mcp_sandbox(mcp_sandbox_factory):
    return mcp_sandbox_factory()


@pytest.fixture
def bound(mcp_sandbox, mcp_manager):
    return BoundContext.bind(mcp_manager.engine, configuration(mcp_sandbox.run_id))
