import pytest

from agent_reliability_lab.agent.config import Budgets
from agent_reliability_lab.evaluation.contracts import ExperimentConfig

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_graph_never_dispatches_provider_when_usage_bound_unknown(lab):
    runner, run = lab
    config = ExperimentConfig(transport="memory", budgets=Budgets(max_known_tokens=20))
    _, [(trial, result)] = await run(["normal_order_status"], config)
    execution = trial["evidence"]["execution"]
    assert execution["status"] == "budget_exhausted"
    assert execution["llm_calls"] == 0
    assert execution["tool_calls"] == 0
    assert not trial["evidence"]["requests"]
    assert not result.objective_success
