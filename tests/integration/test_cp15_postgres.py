import asyncio
import csv
import io
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
import sqlalchemy as sa

from agent_reliability_lab.agent.errors import BudgetExceeded, ModelFailure
from agent_reliability_lab.evaluation.tables import trials
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import starter_draft
from agent_reliability_lab.research.persistence import ResearchStore
from agent_reliability_lab.research.pilot import (
    draft_pilot,
    render_pilot,
    run_pilot,
    validate_plan,
    verify_pilot_report,
)
from agent_reliability_lab.research.pilot_budget import PilotBudgetBroker, ledgers
from agent_reliability_lab.research.pilot_contracts import CallRequest, ProviderObservation
from agent_reliability_lab.research.pilot_model import OfflinePilotModel

pytestmark = pytest.mark.integration


@pytest.fixture
def pilot_factory(manager, monkeypatch):
    monkeypatch.setenv("OPSDESK_TEST_OWNED", "1")

    def build(**changes):
        store = ResearchStore(manager.engine, "test_cp15_" + uuid.uuid4().hex)
        asyncio.run(store.initialize())
        dataset, protocol = starter_draft(repetitions=2)
        scenario = "multi_step_resolve_task"
        protocol = protocol.model_copy(
            update=dict(
                scenarios=[scenario],
                scripts={scenario: protocol.scripts[scenario]},
                planned_pairs=2,
            )
        )
        store.append(dataset)
        ref = store.append(protocol)
        plan = draft_pilot(store, ref, "cp15_test")
        plan.limits = plan.limits.model_copy(update=changes)
        return store, plan

    return build


def open_ledger(store, plan):
    broker = PilotBudgetBroker(store.engine, store.scope, plan)
    broker.initialize()
    arms = validate_plan(store, plan)
    broker.open(plan, arms)
    return broker, arms[0]


def call(plan, arm, **overrides):
    return CallRequest(
        **(
            dict(
                attempt_id=uuid.uuid4().hex,
                execution_id=uuid.uuid4().hex,
                allocation=arm,
                turn=0,
                model_config_hash=digest(plan.model.model_dump(mode="json")),
                pricing_hash=plan.pricing_hash,
                input_hash=digest("input"),
                estimated_input_tokens=17,
                maximum_output_tokens=arm.maximum_output_tokens,
            )
            | overrides
        )
    )


@pytest.mark.parametrize("limit", ["calls", "usd"])
def test_competition_for_last_budget_unit_has_one_winner(pilot_factory, limit):
    store, plan = pilot_factory(total_calls=1 if limit == "calls" else 6)
    if limit == "usd":
        plan.limits = plan.limits.model_copy(
            update=dict(
                maximum_usd=plan.price_ceiling(
                    plan.limits.maximum_input_tokens,
                    validate_plan(store, plan)[0].maximum_output_tokens,
                )
            )
        )
    broker, arm = open_ledger(store, plan)
    contenders = [call(plan, arm) for _ in range(6)]
    barrier = Barrier(len(contenders))

    def attempt(request):
        barrier.wait(timeout=10)
        try:
            broker.reserve(request)
        except BudgetExceeded as error:
            return str(error)
        return request.attempt_id

    with ThreadPoolExecutor(max_workers=len(contenders)) as workers:
        results = list(workers.map(attempt, contenders))
    assert results.count("pilot_provider_calls" if limit == "calls" else "pilot_usd") == 5
    (reservation,) = broker.snapshot()
    assert reservation["attempt_id"] in results
    winner = next(
        request for request in contenders if request.attempt_id == reservation["attempt_id"]
    )
    with ThreadPoolExecutor(max_workers=6) as workers:
        assert (
            sum(value is not None for value in workers.map(broker.begin_dispatch, [winner] * 6))
            == 1
        )
    assert [row["kind"] for row in broker.snapshot()] == ["reserved", "dispatched"]


def test_replay_scoping_and_frozen_manifests(pilot_factory):
    store, plan = pilot_factory()
    broker, arm = open_ledger(store, plan)
    request = call(plan, arm)
    assert broker.reserve(request) == broker.reserve(request)
    for change in (
        dict(allocation=arm.model_copy(update={"tenant": "wrong_tenant"})),
        dict(pricing_hash=digest("some new price")),
        dict(model_config_hash=digest("unsupported model")),
        dict(execution_id=uuid.uuid4().hex),
    ):
        with pytest.raises(ValueError, match="conflicting physical"):
            broker.reserve(request.model_copy(update=change))
        if "execution_id" not in change:
            with pytest.raises(ValueError, match="frozen pilot"):
                broker.reserve(call(plan, arm, **change))
    with pytest.raises(ValueError, match="ledger identity"):
        PilotBudgetBroker(store.engine, "wrong_scope", plan).reserve(request)
    second = plan.model_copy(update={"ledger_id": uuid.uuid4().hex})
    other, _ = open_ledger(store, second)
    with pytest.raises(ValueError, match="conflicting physical"):
        other.reserve(request)
    assert len(broker.snapshot()) == 1 and not other.snapshot()


@pytest.mark.parametrize(
    "limit,key",
    [
        (dict(total_tokens=1), "pilot_total_tokens"),
        (dict(maximum_usd=Decimal("0.000000001")), "pilot_usd"),
        (dict(maximum_input_tokens=1), "pilot_per_request_tokens"),
    ],
)
def test_exhausted_resources_fail_before_dispatch(pilot_factory, limit, key):
    store, plan = pilot_factory(**limit)
    broker, arm = open_ledger(store, plan)
    with pytest.raises(BudgetExceeded, match=key):
        broker.reserve(call(plan, arm))
    assert broker.snapshot() == []


def test_restart_cancellation_unknown_and_billable_failure(pilot_factory):
    store, plan = pilot_factory(total_calls=1)
    broker, arm = open_ledger(store, plan)
    stale = call(plan, arm)
    broker.reserve(stale)
    restarted = PilotBudgetBroker(store.engine, store.scope, plan)
    assert restarted.cancel_pending(stale)
    assert not restarted.begin_dispatch(stale)
    request = call(plan, arm)
    with pytest.raises(ValueError, match="unknown or conflicting physical"):
        restarted.begin_dispatch(request)
    restarted.reserve(request)
    assert restarted.begin_dispatch(request)
    restarted.mark_uncertain(request)
    assert not restarted.cancel_pending(request)
    unknown = ProviderObservation(outcome="failed", reported_model=plan.model.model_id)
    assert restarted.observe(request, unknown)["state"] == "observed"
    with pytest.raises(BudgetExceeded, match="pilot_provider_calls"):
        restarted.reserve(call(plan, arm))
    before = restarted.snapshot()
    reported = unknown.model_copy(
        update=dict(input_tokens=35, output_tokens=3, billed_usd=Decimal("0.01"))
    )
    settled = PilotBudgetBroker(store.engine, store.scope, plan).observe(request, reported)
    assert settled["state"] == "settled" and Decimal(settled["charged_usd"]) == Decimal("0.01")
    assert restarted.observe(request, reported) == settled
    assert restarted.snapshot(len(before)) == before
    with pytest.raises(ValueError, match="conflicting provider observation"):
        restarted.observe(request, reported.model_copy(update={"input_tokens": 34}))
    assert [row["kind"] for row in restarted.snapshot()][-2:] == ["observed", "settled"]


def test_retries_cost_separate_calls_and_hold_deadline(pilot_factory):
    store, plan = pilot_factory(calls_per_scenario=2, retries_per_turn=1, total_retries=1)
    broker, arm = open_ledger(store, plan)
    base = call(plan, arm)
    broker.reserve(base)
    broker.begin_dispatch(base)
    broker.mark_uncertain(base)
    retry = call(plan, arm, execution_id=base.execution_id, retry_of=base.attempt_id)
    assert broker.reserve(retry)["reserved_usd"] == broker.reserve(base)["reserved_usd"]
    assert broker.begin_dispatch(retry)
    broker.mark_uncertain(retry)
    with pytest.raises(BudgetExceeded, match="pilot_provider_retries"):
        broker.reserve(call(plan, arm, execution_id=base.execution_id, retry_of=retry.attempt_id))
    with pytest.raises(BudgetExceeded, match="pilot_provider_calls"):
        broker.reserve(call(plan, arm))
    with store.engine.begin() as connection:
        connection.execute(
            ledgers.update()
            .where(ledgers.c.ledger_id == plan.ledger_id)
            .values(deadline=sa.func.clock_timestamp())
        )
    with pytest.raises(BudgetExceeded, match="pilot_experiment_deadline"):
        broker.reserve(call(plan, arm, turn=1))


def test_bound_breach_freezes_more_dispatches(pilot_factory):
    store, plan = pilot_factory()
    broker, arm = open_ledger(store, plan)
    active, pending = call(plan, arm), call(plan, arm)
    broker.reserve(active)
    broker.reserve(pending)
    broker.begin_dispatch(active)
    record = broker.observe(
        active,
        ProviderObservation(
            outcome="completed",
            reported_model="unexpected-model",
            input_tokens=1,
            output_tokens=2,
        ),
    )
    assert record["state"] == "breached"
    assert record["observation"]["reported_model"] == "unexpected-model"
    with pytest.raises(BudgetExceeded, match="pilot_provider_bound_breach"):
        broker.begin_dispatch(pending)


def test_no_direct_calls_or_live_activation(pilot_factory):
    store, plan = pilot_factory()
    protocol = store.get(plan.protocol)
    broker, arm = open_ledger(store, plan)
    model = OfflinePilotModel(broker, plan, arm, plan.protocol, protocol.model)
    with pytest.raises(ModelFailure, match="pilot_requires_durable_model_request"):
        asyncio.run(model.decide([], [], 0, 16))
    assert broker.snapshot() == []
    live = plan.model_copy(
        update={
            "version": 2,
            "supersedes": store.append(plan),
            "ledger_id": uuid.uuid4().hex,
            "mode": "future_live_requested",
        }
    )
    with pytest.raises(ValueError, match="live pilot execution is disabled"):
        asyncio.run(run_pilot(store, store.append(live)))
    with pytest.raises(ValueError, match="incorrect|plan|live"):
        asyncio.run(run_pilot(store, protocol.dataset))


@pytest.mark.parametrize("fault", ["none", "first_dispatch_timeout", "first_usage_missing"])
def test_full_paired_pilot_reproduces_evidence_and_exports(pilot_factory, fault, monkeypatch):
    store, plan = pilot_factory()
    plan.fixture_fault = fault
    monkeypatch.setenv("OPENAI_API_KEY", "deliberately-unused")
    reference = asyncio.run(run_pilot(store, store.append(plan)))
    frozen = store.get(reference)
    readonly = ResearchStore(store.engine.execution_options(postgresql_readonly=True), store.scope)
    result = verify_pilot_report(readonly, frozen)
    files = render_pilot(result)
    assert files == render_pilot(verify_pilot_report(readonly, frozen))
    assert json.loads(files["json"]) == result
    csv_rows = list(csv.DictReader(io.StringIO(files["csv"])))
    assert [
        json.loads(row["value_json"]) for row in csv_rows if row["category"] == "provider_event"
    ] == result["provider_events"]
    assert result["event_hash"] in files["md"]
    assert result["benchmark"]["started_trials"] == 4
    assert result["benchmark"]["planned_pairs"] == 2
    assert sorted(row["order"] for row in result["benchmark"]["pairs"]) == [
        ["baseline", "guarded"],
        ["guarded", "baseline"],
    ]
    assert all(row["score_pinned_evidence_available"] for row in result["arm_inventory"])
    usage = result["usage"]
    assert usage["physical_dispatches"] > 0
    assert usage["dispatched_unsettled"] == (2 if fault != "none" else 0)
    assert usage["unobserved_dispatch_outcomes"] == (2 if fault == "first_dispatch_timeout" else 0)
    if fault == "none":
        assert all(row["comparison"] == "verified" for row in result["benchmark"]["pairs"])
        trial = result["benchmark"]["pairs"][0]["arms"]["baseline"]["trial_id"]
        evidence = store.evaluations.trial(trial)["evidence"]
        evidence["observed_seconds"] += 1
        with store.engine.begin() as connection:
            connection.execute(
                sa.text("ALTER TABLE opsdesk_evaluation.trials DISABLE TRIGGER USER")
            )
            try:
                connection.execute(
                    trials.update()
                    .where(trials.c.trial_id == trial)
                    .values(evidence=evidence, evidence_hash=digest(evidence))
                )
            finally:
                connection.execute(
                    sa.text("ALTER TABLE opsdesk_evaluation.trials ENABLE TRIGGER USER")
                )
        with pytest.raises(ValueError, match="does not pin|evidence"):
            verify_pilot_report(readonly, frozen)
