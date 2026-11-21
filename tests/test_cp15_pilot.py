import asyncio
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_reliability_lab.agent.config import ModelConfig
from agent_reliability_lab.evaluation.contracts import ExperimentConfig, ModelPrice, PriceBook
from agent_reliability_lab.evaluation.runner import ScenarioRunner
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.cli import main
from agent_reliability_lab.research.contracts import Reference, parse_artifact
from agent_reliability_lab.research.pilot_contracts import (
    PilotLimits,
    PilotModel,
    PilotPlan,
    ProviderObservation,
)


def pricing_plan():
    price = PriceBook(
        version="fixture",
        prices=[
            ModelPrice(
                provider="openai",
                model_id="fixture-v1",
                effective_from=datetime(2025, 1, 1, tzinfo=UTC),
                provenance="fake",
                input_rate=Decimal("3"),
                cached_input_rate=Decimal("4"),
                output_rate=Decimal("7"),
                fixed_request_fee=Decimal("0.01"),
            )
        ],
    )
    return PilotPlan(
        identity="pilot_test",
        author="test_author",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        mode="offline_fixture",
        ledger_id="0" * 32,
        schedule_hash="1" * 64,
        protocol=Reference(
            kind="benchmark_protocol", identity="protocol_test", version=1, content_hash="2" * 64
        ),
        model=PilotModel(model_id="fixture-v1", allowed_models=("fixture-v1",)),
        pricing=price,
        pricing_hash=digest(price.model_dump(mode="json")),
        limits=PilotLimits(
            total_calls=2,
            calls_per_scenario=1,
            retries_per_turn=0,
            maximum_input_tokens=4000,
            maximum_output_tokens=500,
            total_tokens=9000,
            maximum_usd=Decimal("0.2"),
            duration_seconds=10,
        ),
    )


def test_versioned_price_bound_and_reference_round_trip():
    plan = pricing_plan()
    assert plan.price_ceiling(1000, 200) == Decimal("0.0154")
    assert parse_artifact(plan.model_dump(mode="json")) == plan
    body = plan.model_dump(mode="json")
    body["pricing"]["prices"][0]["output_rate"] = "6"
    with pytest.raises(ValidationError, match="manifest fingerprint differs"):
        parse_artifact(body)


def test_missing_price_and_model_mismatch_fail_closed():
    body = pricing_plan().model_dump(mode="json")
    body["model"]["model_id"] = "other-v1"
    body["model"]["allowed_models"].append("other-v1")
    with pytest.raises(ValidationError, match="pricing and model"):
        parse_artifact(body)
    del body["pricing"]
    with pytest.raises(ValidationError, match="pricing"):
        parse_artifact(body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_tokens", -1),
        ("output_tokens", True),
        ("billed_usd", Decimal("NaN")),
        ("billed_usd", Decimal("-0.01")),
    ],
)
def test_invalid_usage_cannot_create_capacity(field, value):
    with pytest.raises(ValidationError):
        ProviderObservation(outcome="failed", **{field: value})


def test_cli_cannot_request_live_execution(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-value")
    monkeypatch.setattr(
        sys, "argv", ["opsdesk-research", "benchmark-pilot-run", "missing.json", "--live"]
    )
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 2
    assert "unrecognized arguments: --live" in capsys.readouterr().err


def test_benchmark_runner_rejects_direct_openai_adapter_even_with_legacy_opt_in():
    runner = object.__new__(ScenarioRunner)
    config = ExperimentConfig(model=ModelConfig(provider="openai", model_id="mock-v1"))
    with pytest.raises(ValueError, match="disabled in benchmark mode"):
        asyncio.run(runner.run([Path("never-read.json")], config, live=True, benchmark_context={}))


def test_benchmark_runner_rejects_an_unbrokered_model_factory_before_invoking_it():
    def forbidden(_):
        pytest.fail("benchmark started a model factory outside the broker")

    runner = object.__new__(ScenarioRunner)
    with pytest.raises(ValueError, match="arbitrary model factories are disabled"):
        asyncio.run(
            runner.run(
                [Path("never-read.json")],
                ExperimentConfig(),
                model_factory=forbidden,
                benchmark_context={},
            )
        )
