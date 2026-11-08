import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_reliability_lab.evaluation.contracts import ModelPrice, PriceBook
from agent_reliability_lab.evaluation.metrics import price_execution, summarize
from agent_reliability_lab.evaluation.scoring import score
from agent_reliability_lab.evaluation.statistics import nearest_rank, wilson


@pytest.mark.parametrize(
    "values,expected",
    [([], None), ([3.0], 3.0), ([float(i) for i in range(1, 21)], 19.0), ([1.0, 4.0, 2.0], 4.0)],
)
def test_p95_nearest_rank(values, expected):
    assert nearest_rank(values) == expected


@pytest.mark.parametrize("values", [[-1.0], [float("nan")], [float("inf")]])
def test_invalid_durations(values):
    with pytest.raises(ValueError):
        nearest_rank(values)


def test_wilson_known_values_and_empty_denominator():
    assert wilson(0, 0) is None
    assert wilson(4, 4) == pytest.approx([0.5101091635454027, 1.0])
    assert wilson(0, 10) == pytest.approx([0.0, 0.2775327998628892])
    assert wilson(5, 10) == pytest.approx([0.236593090512564, 0.763406909487436])
    with pytest.raises(ValueError):
        wilson(2, 1)


def test_exact_success_denominator_and_unknown_evidence(normal_data):
    good = score(*normal_data)
    bad = good.model_copy(deep=True, update={"trial_id": "bad", "objective_success": False})
    unknown = good.model_copy(deep=True, update={"trial_id": "unknown", "objective_success": None})
    excluded = good.model_copy(
        deep=True,
        update={"trial_id": "excluded", "eligible": False, "exclusion_reason": "setup_failed"},
    )
    result = summarize([good, bad, unknown, excluded])
    assert result["metrics"]["task_success_rate"]["value"] == pytest.approx(1 / 3)
    assert result["eligible_count"] == 3 and result["excluded_count"] == 1
    assert result["outcome_rates"]["verified_failure"]["value"] == pytest.approx(1 / 3)
    assert result["outcome_rates"]["unverified"]["value"] == pytest.approx(1 / 3)
    assert result["metrics"]["task_success_rate"]["unverified_count"] == 1
    assert any("Repeated" in warning for warning in result["warnings"])
    assert any("20" in warning for warning in result["warnings"])
    with pytest.raises(ValueError, match="duplicate"):
        summarize([good, good])


def test_missing_usage_prices_and_zero_success_are_not_zero_cost(normal_data):
    result = score(*normal_data)
    live = result.model_copy(
        deep=True,
        update={
            "mode": "live",
            "objective_success": False,
            "cost": {"status": "unavailable", "known_spend": "0.1"},
        },
    )
    summary = summarize([live])
    cost = summary["metrics"]["cost_per_successful_task"]
    assert cost["value"] is None and cost["reason"] == "no_successful_tasks"
    assert cost["known_spend_lower_bound"] == "0.1"
    assert summary["token_usage"]["input_tokens"]["covered_trials"] == 0
    assert summarize([])["metrics"]["task_success_rate"]["value"] is None


def test_failed_trials_spend_is_included(normal_data):
    result = score(*normal_data)
    good = result.model_copy(
        deep=True, update={"mode": "live", "cost": {"status": "available", "known_spend": "0.2"}}
    )
    bad = good.model_copy(
        deep=True,
        update={
            "trial_id": "failed",
            "objective_success": False,
            "cost": {"status": "available", "known_spend": "0.3"},
        },
    )
    summary = summarize([good, bad])
    assert summary["metrics"]["cost_per_successful_task"]["value"] == "0.5"
    bad.cost["status"] = "unavailable"
    assert summarize([good, bad])["metrics"]["cost_per_successful_task"]["value"] is None


def test_recovery_and_attack_metrics_require_exposure(normal_data):
    result = score(*normal_data)
    summary = summarize([result])
    assert summary["metrics"]["recovery_rate"]["denominator"] == 0
    assert summary["metrics"]["prompt_injection_attack_success_rate"]["value"] is None
    # Unit-level records test the formula, not an implemented injection harness.
    exposed = result.model_copy(
        update={
            "recovery_eligible": True,
            "recovered": True,
            "attack_eligible": True,
            "attacker_success": False,
        }
    )
    summary = summarize([exposed])
    assert summary["metrics"]["recovery_rate"]["value"] == 1.0
    assert summary["metrics"]["prompt_injection_attack_success_rate"]["value"] == 0.0


def price_book():
    # Explicit synthetic prices solely for arithmetic tests, never API pricing claims.
    return PriceBook.model_validate_json(
        json.dumps(
            {
                "version": "synthetic_test_v1",
                "prices": [
                    {
                        "provider": "openai",
                        "model_id": "synthetic_snapshot",
                        "effective_from": "2020-01-01T00:00:00Z",
                        "provenance": "https://prices.opsdesk.invalid/test",
                        "input_rate": "2",
                        "output_rate": "4",
                        "cached_input_rate": "1",
                    }
                ],
            }
        )
    )


def test_versioned_price_math_and_overlapping_tokens(normal_data):
    evidence = normal_data[2]
    evidence.execution["config"]["model"]["provider"] = "openai"
    evidence.requests = [
        {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "model": "synthetic_snapshot",
            "usage": {
                "source": "provider",
                "input_tokens": 1000000,
                "cached_input_tokens": 200000,
                "output_tokens": 100000,
                "reasoning_tokens": 50000,
            },
        }
    ]
    cost = price_execution(evidence, "live", price_book())
    assert float(cost["amount"]) == pytest.approx(2.2)
    # Reasoning is already included in output; it is not billed twice.
    evidence.requests[0]["usage"]["cached_input_tokens"] = None
    assert price_execution(evidence, "live", price_book())["amount"] is None
    assert price_execution(evidence, "scripted", None)["status"] == "not_applicable"


@pytest.mark.parametrize("missing", ["usage", "price", "model", "timestamp"])
def test_price_missingness(normal_data, missing):
    evidence = normal_data[2]
    evidence.execution["config"]["model"]["provider"] = "openai"
    evidence.requests[0]["usage"] = {
        "source": "provider",
        "input_tokens": 2,
        "output_tokens": 3,
        "cached_input_tokens": 0,
    }
    evidence.requests[0]["model"] = "synthetic_snapshot"
    evidence.requests = evidence.requests[:1]
    book = price_book()
    if missing == "price":
        book = None
    else:
        evidence.requests[0][missing] = None
    assert price_execution(evidence, "live", book)["amount"] is None


def test_price_intervals_do_not_overlap():
    book = price_book()
    with pytest.raises(ValidationError, match="overlap"):
        PriceBook(version="bad", prices=[book.prices[0], book.prices[0]])
    with pytest.raises(ValidationError):
        ModelPrice(
            provider="openai",
            model_id="test",
            effective_from=datetime.now(UTC),
            provenance="test",
            input_rate=-1,
            output_rate=1,
        )


def test_unexpected_host_errors_remain_quarantined_on_rescore(normal_data):
    evidence = normal_data[2]
    evidence.execution["status"] = "failed"
    evidence.execution["result"]["reason"] = "execution_error"
    result = score(*normal_data)
    assert result.status == "infrastructure_failure" and not result.eligible
    assert result.objective_success is None and result.evidence_hash


def test_source_commit_required_outside_git(monkeypatch):
    from types import SimpleNamespace

    from agent_reliability_lab.evaluation.contracts import ExperimentConfig
    from agent_reliability_lab.evaluation.runner import provenance

    monkeypatch.setattr(
        "agent_reliability_lab.evaluation.runner.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    with pytest.raises(ValueError, match="source_commit"):
        provenance(ExperimentConfig())
    result = provenance(ExperimentConfig(source_commit="1" * 40))
    assert result["source_commit"] == "1" * 40 and result["working_tree_dirty"] is None
