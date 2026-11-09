from decimal import Decimal

import pytest

from agent_reliability_lab.agent.budgets import before_model_call
from agent_reliability_lab.agent.config import AgentConfig, Budgets, ModelConfig
from agent_reliability_lab.agent.errors import BudgetExceeded


def config(**limits):
    return AgentConfig(
        sandbox_run_id="test_budget",
        actor_id="actor_support",
        tenant_id="tenant_ops",
        budgets=Budgets(**limits),
        model=ModelConfig(
            script=[
                dict(
                    answer="synthetic",
                    usage=dict(input_tokens=5, output_tokens=3, source="scripted"),
                )
            ]
        ),
    )


def test_known_token_limit_stops_before_call():
    c = config(max_known_tokens=10)
    before_model_call(c, dict(request_count=0), 0)
    with pytest.raises(BudgetExceeded, match="cumulative_known_tokens"):
        before_model_call(c, dict(request_count=1, input_tokens=5, output_tokens=3), 0)


def test_incomplete_prior_usage_fails_closed():
    with pytest.raises(BudgetExceeded, match="unknown_cumulative_usage"):
        before_model_call(config(max_known_tokens=10), dict(request_count=1), 0)


def test_cost_capped_live_calls_disabled_without_reservation_guarantee():
    c = config(max_estimated_cost=Decimal("1"))
    c.model = ModelConfig(provider="openai", model_id="explicit-model")
    with pytest.raises(BudgetExceeded, match="capped_live_execution_unsupported"):
        before_model_call(c, dict(request_count=0), 0)


def test_synthetic_cost_cap_requires_versioned_exact_price():
    c = config(max_estimated_cost=Decimal("0.000007"))
    with pytest.raises(BudgetExceeded, match="versioned_price_schedule_required"):
        before_model_call(c, dict(request_count=0), 0)
    c.budgets.price_schedule = dict(
        schema_version="1.0",
        version="synthetic-test-v1",
        currency="USD",
        prices=[
            dict(
                provider="fake",
                model_id="scripted-v1",
                effective_from="2020-01-01T00:00:00Z",
                provenance="Synthetic test rates, not actual provider pricing.",
                input_rate="1",
                output_rate="1",
            )
        ],
    )
    with pytest.raises(BudgetExceeded, match="estimated_provider_cost"):
        before_model_call(c, dict(request_count=0), 0)
    c.budgets.max_estimated_cost = Decimal("0.000008")
    before_model_call(c, dict(request_count=0), 0)


def test_unknown_fake_usage_never_fabricated():
    c = config(max_known_tokens=10)
    c.model.script = [dict(answer="No usage available.")]
    with pytest.raises(BudgetExceeded, match="unknown_pre_call_token_bound"):
        before_model_call(c, dict(request_count=0), 0)
