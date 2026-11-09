"""Pre-call reservations only when an adapter supplies a defensible upper bound."""

import json
from datetime import UTC, datetime
from decimal import Decimal

from agent_reliability_lab.agent.errors import BudgetExceeded


def scripted_bound(model, turn):
    script = model.script
    if not script or turn >= len(script) and not model.repeat_last:
        return None
    row = script[min(turn, len(script) - 1) if model.repeat_last else turn]

    def bound(payload):
        if "if_observation" in payload:
            alternatives = [bound(payload[key]) for key in ("then", "else")]
            if any(v is None for v in alternatives):
                return None
            return tuple(max(v[i] for v in alternatives) for i in (0, 1))
        usage = payload.get("usage") or {}
        counts = [usage.get(key) for key in ("input_tokens", "output_tokens")]
        if any(type(v) is not int or v < 0 for v in counts):
            return None
        return tuple(counts)

    return bound(row)


def before_model_call(config, usage, turn):
    limits = config.budgets
    token_cap, cost_cap = limits.max_known_tokens, limits.max_estimated_cost
    if token_cap is None and cost_cap is None:
        return
    if config.model.provider != "fake":
        # This SDK cannot reserve a guaranteed provider input/spend ceiling.
        raise BudgetExceeded("capped_live_execution_unsupported_requires_provider_spending_limit")
    bound = scripted_bound(config.model, turn)
    if bound is None:
        raise BudgetExceeded("unknown_pre_call_token_bound")
    prior = [usage.get(key) for key in ("input_tokens", "output_tokens")]
    if usage.get("request_count", 0) == 0:
        prior = [0, 0]
    if any(v is None for v in prior):
        raise BudgetExceeded("unknown_cumulative_usage")
    if token_cap is not None and sum(prior) + sum(bound) > token_cap:
        raise BudgetExceeded("cumulative_known_tokens")
    if cost_cap is not None:
        from agent_reliability_lab.evaluation.contracts import PriceBook

        if limits.price_schedule is None:
            raise BudgetExceeded("versioned_price_schedule_required")
        book = PriceBook.model_validate_json(json.dumps(limits.price_schedule))
        now = datetime.now(UTC)
        prices = [
            p
            for p in book.prices
            if p.provider == config.model.provider
            and p.model_id == config.model.model_id
            and p.effective_from <= now
            and (p.effective_until is None or now < p.effective_until)
        ]
        if len(prices) != 1:
            raise BudgetExceeded("applicable_exact_model_price_required")
        price = prices[0]
        # Worst input rate avoids assuming cache discounts. Scripted spend is synthetic only.
        inputs = Decimal(prior[0] + bound[0]) * max(price.input_rate, price.cached_input_rate or 0)
        outputs = Decimal(prior[1] + bound[1]) * price.output_rate
        estimated = (inputs + outputs) / Decimal(1000000) + (
            usage.get("request_count", 0) + 1
        ) * price.fixed_request_fee
        if estimated > cost_cap:
            raise BudgetExceeded("estimated_provider_cost")
