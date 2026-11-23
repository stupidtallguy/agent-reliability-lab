from itertools import product

import pytest

from agent_reliability_lab.adversarial.contracts import Defense, GuardFactors, WriteScope
from agent_reliability_lab.adversarial.defenses import blocks, frame
from agent_reliability_lab.agent.config import AgentConfig, ModelConfig
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.guard_ablation import factorial_orders


@pytest.mark.parametrize(("system", "framing", "scope"), tuple(product((False, True), repeat=3)))
def test_factors_are_independent_and_legacy_defaults_remain(system, framing, scope):
    factors = GuardFactors(
        system_policy=system, observation_framing=framing, task_scope_filter=scope
    )
    defense = Defense(
        configuration="guarded",
        factors=factors,
        write_scopes=[
            WriteScope(
                tool="update_task",
                arguments={"task_id": "task_001", "patch": {"status": "resolved"}},
            )
        ],
    )
    assert defense.adds_system_policy is system
    assert defense.frames_observations is framing
    obs = {"data": {"status": "shipped"}, "error": None}
    assert (frame(obs, defense) != obs) is framing
    bad = {"task_id": "task_001", "expected_version": 1, "patch": {"status": "in_progress"}}
    assert blocks(defense, "update_task", bad) is scope
    assert not blocks(defense, "update_task", bad | {"patch": {"status": "resolved"}})
    legacy = Defense(configuration="guarded", write_scopes=defense.write_scopes)
    assert "factors" not in legacy.model_dump()
    assert legacy.adds_system_policy and legacy.frames_observations and legacy.filters_task_writes


def test_balanced_order_and_factor_commitments():
    orders = factorial_orders(42)
    cells = [[digest(factors[arm]) for arm in order] for _, order, factors in orders]
    first = [cell for pair in cells[:4] for cell in pair]
    second = [cell for pair in cells[4:] for cell in pair]
    assert len(set(first)) == 8 and second == first[::-1]
    assert digest(orders) != digest(factorial_orders(43))
    for _, order, factors in orders:
        assert set(order) == {"baseline", "guarded"}
        assert factors["baseline"] | {"task_scope_filter": True} == factors["guarded"]


def test_cloud_host_config_cannot_accept_ablated_factors():
    with pytest.raises(ValueError, match="only to the local Ollama study"):
        AgentConfig(
            sandbox_run_id="eval_case",
            actor_id="actor_001",
            tenant_id="opsdesk",
            model=ModelConfig(provider="openai", model_id="fixture_model"),
            defense=Defense(
                factors=GuardFactors(
                    system_policy=True, observation_framing=False, task_scope_filter=False
                )
            ),
        )
