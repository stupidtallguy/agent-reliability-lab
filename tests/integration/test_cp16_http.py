import asyncio
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier

import httpx
import httpx2
import pytest

from agent_reliability_lab.agent.config import ModelConfig
from agent_reliability_lab.agent.errors import BudgetExceeded, ModelFailure
from agent_reliability_lab.agent.models.fake import ScriptedModel
from agent_reliability_lab.evaluation.contracts import ModelPrice, PriceBook
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import execute_benchmark, starter_draft
from agent_reliability_lab.research.live import (
    ActivationBlocked,
    draft_authorization,
    draft_live,
    preflight,
    run_provider_pilot,
)
from agent_reliability_lab.research.live_contracts import ProviderProfile
from agent_reliability_lab.research.live_model import LiveHTTPModel, _PermitTransport, chat_payload
from agent_reliability_lab.research.persistence import ResearchStore
from agent_reliability_lab.research.pilot import render_pilot, validate_plan, verify_pilot_report
from agent_reliability_lab.research.pilot_budget import PilotBudgetBroker
from agent_reliability_lab.research.pilot_contracts import CallRequest, ProviderObservation

pytestmark = pytest.mark.integration
MODEL = "fixture-model-2025-01-01"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    async def forbidden(*args):
        pytest.fail("Public HTTP transport is forbidden in the CP16 tests")

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def pilot(manager, monkeypatch):
    monkeypatch.setenv("OPSDESK_TEST_OWNED", "1")
    store = ResearchStore(manager.engine, "test_cp16_" + uuid.uuid4().hex)
    asyncio.run(store.initialize())
    dataset, parent = starter_draft(repetitions=1)
    store.append(dataset)
    parent_ref = store.append(parent)
    profile = ProviderProfile(
        requested_model=MODEL,
        returned_model=MODEL,
        textual_function_tools=True,
        output_limit_supported=True,
        input_ceiling=100000,
        output_ceiling=500,
        price_review="synthetic",
        spend_control="simulation",
        evidence_reference="network_fixture",
        billing="standard_text_rates_and_fixed_fee",
    )
    pricing = PriceBook(
        version="synthetic",
        prices=[
            ModelPrice(
                provider="openai",
                model_id=MODEL,
                effective_from=datetime(2020, 1, 1, tzinfo=UTC),
                provenance="test_fixture",
                input_rate=Decimal("1.25"),
                output_rate=Decimal("5"),
                cached_input_rate=Decimal("0.50"),
            )
        ],
    )
    protocol, plan = draft_live(
        store,
        parent_ref,
        "test_cp16",
        profile,
        pricing,
        Decimal("2.00"),
        "multi_step_resolve_task",
    )
    store.append(protocol)
    plan_ref = store.append(plan)
    auth = draft_authorization(
        store, plan_ref, profile, "mock_http", datetime.now(UTC) + timedelta(minutes=15)
    )
    return store, parent, plan, plan_ref, auth


def open_budget(pilot):
    store, _, plan, _, auth = pilot
    auth_ref = store.append(auth)
    broker = PilotBudgetBroker(store.engine, store.scope, plan, authorization=auth_ref)
    broker.initialize()
    arms = validate_plan(store, plan)
    broker.open(plan, arms)
    return broker, arms[0], auth_ref


def request_for(pilot, arm, ref, payload):
    return CallRequest(
        attempt_id=uuid.uuid4().hex,
        execution_id=uuid.uuid4().hex,
        allocation=arm,
        turn=0,
        model_config_hash=pilot[-1].configuration_hash,
        pricing_hash=pilot[2].pricing_hash,
        input_hash=digest([payload["messages"], payload.get("tools", [])]),
        estimated_input_tokens=16,
        maximum_output_tokens=arm.maximum_output_tokens,
        wire_hash=digest(payload),
        authorization_hash=ref.content_hash,
    )


def response_body(decision, model=MODEL):
    return dict(
        id="fixture_completion",
        object="chat.completion",
        model=model,
        created=0,
        choices=[
            dict(
                index=0,
                finish_reason="tool_calls" if decision.calls else "stop",
                message=dict(
                    role="assistant",
                    content=decision.answer,
                    tool_calls=[
                        dict(
                            id=call.call_id,
                            type="function",
                            function=dict(name=call.name, arguments=call.arguments_json),
                        )
                        for call in decision.calls
                    ],
                ),
            )
        ],
        usage=dict(
            prompt_tokens=21,
            completion_tokens=8,
            total_tokens=29,
            prompt_tokens_details={"cached_tokens": 3},
        ),
    )


def test_score_pinned_http_pilot_and_preflight(pilot, monkeypatch, tmp_path):
    store, parent, plan, plan_ref, auth = pilot
    reference = store.append(auth)
    readonly = ResearchStore(store.engine.execution_options(postgresql_readonly=True), store.scope)
    assert preflight(readonly, plan_ref)["status"] == "awaiting_operator_authorization"
    readiness = preflight(readonly, plan_ref, reference)
    assert readiness["status"] == "ready_for_mock_validation"
    assert readiness["checks"]["credential_configured"] is False
    key = "test_only_must_never_be_used"
    monkeypatch.setenv("OPENAI_API_KEY", key)
    seen = []
    script = ScriptedModel(ModelConfig(script=parent.scripts["multi_step_resolve_task"]))

    async def handler(request):
        assert request.method == "POST" and str(request.url) == auth.profile.endpoint
        assert key not in request.headers["authorization"]
        body = json.loads(request.content)
        assert (body["model"], body["max_completion_tokens"], body["service_tier"]) == (
            MODEL,
            500,
            "default",
        )
        assert body["n"] == 1 and not body["stream"] and not body["store"]
        assert body["tools"] and all(tool["type"] == "function" for tool in body["tools"])
        assert not body["parallel_tool_calls"]
        seen.append(digest(body))
        turn = sum(message["role"] == "assistant" for message in body["messages"])
        decision = await script.decide(body["messages"], body["tools"], turn, 500)
        return httpx2.Response(
            200, json=response_body(decision), headers={"x-request-id": f"fixture-{len(seen)}"}
        )

    frozen = asyncio.run(
        run_provider_pilot(store, reference, mock_transport=httpx2.MockTransport(handler))
    )
    artifact = readonly.get(frozen)
    document = verify_pilot_report(readonly, artifact)
    assert document["interpretation"] == "mock_http"
    assert sorted(pair["order"] for pair in document["benchmark"]["pairs"]) == [
        ["baseline", "guarded"],
        ["guarded", "baseline"],
    ]
    assert all(pair["comparison"] == "verified" for pair in document["benchmark"]["pairs"])
    for pair in document["benchmark"]["pairs"]:
        for arm in pair["arms"].values():
            assert arm["measurements"]["task_success"]["status"] == "verified_success", arm
    sent = [event["body"] for event in document["provider_events"] if event["kind"] == "dispatched"]
    assert len(sent) == len(seen) == document["usage"]["settlements"]
    assert [row["request"]["wire_hash"] for row in sent] == seen
    assert document["usage"]["reported_input_tokens"]["sum_observed"] == 21 * len(seen)
    assert document["authorization"]["content_hash"] == reference.content_hash
    exports = render_pilot(document)
    assert exports == render_pilot(verify_pilot_report(readonly, artifact))
    assert all(key not in content for content in exports.values())
    assert preflight(readonly, plan_ref, reference)["status"] == "blocked"
    path = tmp_path / "plan-ref.json"
    path.write_text(plan_ref.model_dump_json(), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from agent_reliability_lab.research.cli import main; main()",
            "--scope",
            store.scope,
            "benchmark-live-preflight",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["issues"] == ["pilot_ledger_already_opened"]


@pytest.mark.parametrize(
    "variant,code,state",
    [
        ("timeout", "model_timeout", "uncertain"),
        ("connection", "provider_unavailable", "uncertain"),
        (429, "rate_limited", "observed"),
        (500, "provider_error", "observed"),
        (401, "model_unavailable", "observed"),
        ("invalid", "invalid_model_response", "observed"),
        ("missing_usage", None, "observed"),
        ("wrong_model", "pilot_provider_bound_breach", "breached"),
        ("too_many_tokens", "pilot_provider_bound_breach", "breached"),
        ("cache_write", "pilot_provider_bound_breach", "breached"),
        ("contradictory_total", "pilot_provider_bound_breach", "breached"),
        ("unpriced_tier", "pilot_provider_bound_breach", "breached"),
        ("billable_failure", "invalid_model_response", "settled"),
    ],
)
def test_http_failures_are_single_request_and_keep_appropriate_holds(
    pilot, monkeypatch, variant, code, state
):
    store, _, plan, _, auth = pilot
    broker, arm, ref = open_budget(pilot)
    messages = [{"role": "user", "content": "Synthetic test"}]
    payload = chat_payload(MODEL, messages, [], arm.maximum_output_tokens)
    attempt = request_for(pilot, arm, ref, payload)
    counted = []

    def fake(request):
        from agent_reliability_lab.agent.state import Decision

        counted.append(request)
        if variant == "timeout":
            raise httpx2.ReadTimeout("private provider error", request=request)
        if variant == "connection":
            raise httpx2.RemoteProtocolError("lost response", request=request)
        status = variant if isinstance(variant, int) else 200
        body = response_body(Decision(answer="synthetic"))
        if status != 200:
            body = {"error": {"message": "private provider error", "type": "fixture_error"}}
        if variant == "invalid":
            return httpx2.Response(
                200, content=b"not JSON", headers={"content-type": "application/json"}
            )
        if variant == "missing_usage":
            del body["usage"]
        if variant == "wrong_model":
            body["model"] = "other-model"
        if variant == "too_many_tokens":
            body["usage"]["completion_tokens"] = arm.maximum_output_tokens + 1
        if variant == "cache_write":
            body["usage"]["prompt_tokens_details"]["cache_write_tokens"] = 4
        if variant == "contradictory_total":
            body["usage"]["total_tokens"] = 123456
        if variant == "unpriced_tier":
            body["service_tier"] = "priority"
        if variant == "billable_failure":
            body["choices"][0]["finish_reason"] = "length"
        return httpx2.Response(status, json=body, headers={"x-request-id": "fixture-error"})

    model = LiveHTTPModel(
        broker,
        plan,
        arm,
        plan.protocol,
        ModelConfig(provider="openai", model_id=MODEL),
        auth,
        httpx2.MockTransport(fake),
    )
    # The end-to-end case verifies the sealed join. These cases isolate the HTTP boundary.
    monkeypatch.setattr(model, "_bound_request", lambda *args, **kwargs: attempt)

    async def run():
        return await model.decide_for_request(
            attempt.execution_id, attempt.attempt_id, messages, [], 0, arm.maximum_output_tokens
        )

    if code is None:
        assert asyncio.run(run()).usage.input_tokens is None
    else:
        with pytest.raises(ModelFailure, match=code):
            asyncio.run(run())
    actual = broker.snapshot()[-1]["body"]
    assert len(counted) == 1 and actual["state"] == state
    if state in {"observed", "uncertain", "breached"}:
        assert Decimal(actual["charged_usd"]) >= Decimal(actual["reserved_usd"])
    if variant == "billable_failure":
        assert actual["charged_tokens"] == 29 and actual["observation"]["outcome"] == "failed"
    assert "private provider error" not in str(broker.snapshot())
    if state != "breached":
        with pytest.raises(ModelFailure, match="pilot_attempt_already_dispatched"):
            asyncio.run(run())
        assert len(counted) == 1


def test_stale_revoked_mismatched_and_paid_authorization_do_not_dispatch(pilot, monkeypatch):
    store, _, plan, plan_ref, auth = pilot
    requests = []
    mock = httpx2.MockTransport(lambda request: requests.append(request))
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-not-sent")
    with pytest.raises(ValueError, match="registered authorization"):
        asyncio.run(
            execute_benchmark(store, plan.protocol, pilot_ref=plan_ref, mock_transport=mock)
        )
    for update in (
        {"experiment": "wrong_experiment"},
        {"pricing_hash": "0" * 64},
        {"profile": auth.profile.model_copy(update={"requested_model": "other-model"})},
    ):
        with pytest.raises(ActivationBlocked, match="binding_mismatch"):
            store.append(auth.model_copy(update=update))
    paid = auth.model_copy(
        update={
            "mode": "paid_openai",
            "profile": auth.profile.model_copy(
                update={
                    "price_review": "externally_reviewed",
                    "spend_control": "externally_enforced",
                    "provider_project": "proj_test",
                }
            ),
        }
    )
    paid_ref = store.append(paid)
    assert "external_activation_locked" in preflight(store, plan_ref, paid_ref)["issues"]
    with pytest.raises(ActivationBlocked, match="external_activation_locked"):
        asyncio.run(run_provider_pilot(store, paid_ref, activate_paid=True))
    expired = auth.model_copy(
        update={
            "version": 2,
            "supersedes": paid_ref,
            "starts_at": auth.starts_at - timedelta(hours=1),
            "created_at": auth.created_at - timedelta(hours=1),
            "deadline": auth.starts_at - timedelta(minutes=1),
        }
    )
    expired_ref = store.append(expired)
    with pytest.raises(ActivationBlocked, match="outside_execution_window"):
        asyncio.run(run_provider_pilot(store, expired_ref, mock_transport=mock))
    active = auth.model_copy(update={"version": 3, "supersedes": expired_ref})
    active_ref = store.append(active)
    broker = PilotBudgetBroker(store.engine, store.scope, plan, authorization=active_ref)
    broker.initialize()
    arms = validate_plan(store, plan)
    broker.open(plan, arms)
    payload = chat_payload(MODEL, [], [], arms[0].maximum_output_tokens)
    attempt = request_for(pilot, arms[0], active_ref, payload)
    wrong_tenant = attempt.model_copy(
        update={"allocation": arms[0].model_copy(update={"tenant": "wrong_tenant"})}
    )
    with pytest.raises(ValueError, match="frozen pilot allocation"):
        broker.reserve(wrong_tenant)
    broker.reserve(attempt)
    store.append(
        active.model_copy(update={"version": 4, "supersedes": active_ref, "decision": "revoked"})
    )
    gate = _PermitTransport(broker, attempt, active, mock)
    wire = httpx2.Request("POST", active.profile.endpoint, json=payload)
    with pytest.raises(ActivationBlocked, match="superseded"):
        asyncio.run(gate.handle_async_request(wire))
    assert [row["kind"] for row in broker.snapshot()] == ["reserved"]
    assert not requests


def test_http_gate_does_not_invoke_backend_without_reservation_or_exact_wire(pilot):
    broker, arm, ref = open_budget(pilot)
    payload = chat_payload(MODEL, [], [], arm.maximum_output_tokens)
    attempt = request_for(pilot, arm, ref, payload)
    seen = []
    transport = _PermitTransport(broker, attempt, pilot[-1], httpx2.MockTransport(seen.append))

    def wire(body):
        return httpx2.Request("POST", pilot[-1].profile.endpoint, json=body)

    with pytest.raises(ValueError, match="physical provider attempt"):
        asyncio.run(transport.handle_async_request(wire(payload)))
    broker.reserve(attempt)
    with pytest.raises(ModelFailure, match="differs_from_reservation"):
        asyncio.run(transport.handle_async_request(wire(payload | {"model": "other"})))
    assert not seen


def test_cp16_concurrency_with_reconciliation_after_restart(pilot):
    store, _, plan, _, auth = pilot
    new_plan = plan.model_copy(
        update={
            "identity": "test_cp16_contend",
            "ledger_id": uuid.uuid4().hex,
            "limits": plan.limits.model_copy(update={"total_calls": 1, "calls_per_scenario": 1}),
        }
    )
    plan_ref = store.append(new_plan)
    grant = draft_authorization(store, plan_ref, auth.profile, "mock_http", auth.deadline)
    broker, arm, ref = open_budget((store, None, new_plan, plan_ref, grant))
    payload = chat_payload(MODEL, [], [], arm.maximum_output_tokens)
    submissions = [
        request_for((store, None, new_plan, plan_ref, grant), arm, ref, payload) for _ in range(6)
    ]
    gate = Barrier(6)

    def compete(request):
        gate.wait(timeout=10)
        try:
            broker.reserve(request)
        except BudgetExceeded:
            return None
        return request

    with ThreadPoolExecutor(max_workers=6) as workers:
        (winner,) = [result for result in workers.map(compete, submissions) if result is not None]
    code = """
import json, os, sys
from agent_reliability_lab.opsdesk.database import engine_from_env
from agent_reliability_lab.research.contracts import Reference
from agent_reliability_lab.research.pilot_budget import PilotBudgetBroker
from agent_reliability_lab.research.pilot_contracts import CallRequest, PilotPlan
data=json.loads(sys.stdin.read())
broker=PilotBudgetBroker(engine_from_env(),data['scope'],PilotPlan.model_validate_json(json.dumps(data['plan'])),authorization=Reference.model_validate(data['authorization']))
assert broker.begin_dispatch(CallRequest.model_validate_json(json.dumps(data['request'])))
os._exit(29)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(
            dict(
                scope=store.scope,
                plan=new_plan.model_dump(mode="json"),
                authorization=ref.model_dump(mode="json"),
                request=winner.model_dump(mode="json"),
            )
        ),
        text=True,
        capture_output=True,
        env=os.environ.copy(),
        timeout=30,
    )
    assert completed.returncode == 29, completed.stderr
    restarted = PilotBudgetBroker(store.engine, store.scope, new_plan, authorization=ref)
    assert restarted.begin_dispatch(winner) is None and restarted.cancel_pending(winner) is False
    with pytest.raises(BudgetExceeded, match="pilot_provider_calls"):
        restarted.reserve(next(item for item in submissions if item != winner))
    billed = ProviderObservation(
        outcome="failed",
        reported_model=MODEL,
        input_tokens=21,
        output_tokens=8,
        billed_usd=Decimal("0.75"),
    )
    assert restarted.observe(winner, billed)["state"] == "breached"
    assert restarted.observe(winner, billed)["state"] == "breached"
    assert [row["kind"] for row in restarted.snapshot()] == [
        "reserved",
        "dispatched",
        "observed",
        "breached",
    ]


def test_alias_heldout_and_exhausted_budget_cannot_reach_http(pilot, monkeypatch):
    store, parent, plan, _, auth = pilot
    alias = auth.profile.model_copy(
        update={"requested_model": "fixture-model", "returned_model": "fixture-model"}
    )
    assert alias.incompatibilities("mock_http") == ["model_alias_or_identity_incompatible"]
    with pytest.raises(ActivationBlocked, match="existing_development_protocol_required"):
        draft_live(
            store,
            store.reference(parent),
            "invalid",
            auth.profile,
            plan.pricing,
            Decimal("2"),
            "private_case",
        )
    tiny = plan.model_copy(
        update={
            "identity": "test_exhausted",
            "ledger_id": uuid.uuid4().hex,
            "limits": plan.limits.model_copy(update={"maximum_usd": Decimal("0.01")}),
        }
    )
    tiny_ref = store.append(tiny)
    grant = draft_authorization(store, tiny_ref, auth.profile, "mock_http", auth.deadline)
    broker, arm, ref = open_budget((store, None, tiny, tiny_ref, grant))
    seen = []
    model = LiveHTTPModel(
        broker,
        tiny,
        arm,
        tiny.protocol,
        ModelConfig(provider="openai", model_id=MODEL),
        grant,
        httpx2.MockTransport(seen.append),
    )
    with pytest.raises(ModelFailure, match="durable_model_request"):
        asyncio.run(model.decide([], [], 0, arm.maximum_output_tokens))
    attempt = request_for(
        (store, None, tiny, tiny_ref, grant),
        arm,
        ref,
        chat_payload(MODEL, [], [], arm.maximum_output_tokens),
    )
    monkeypatch.setattr(model, "_bound_request", lambda *args, **kwargs: attempt)
    with pytest.raises(BudgetExceeded, match="pilot_usd"):
        asyncio.run(
            model.decide_for_request(
                attempt.execution_id, attempt.attempt_id, [], [], 0, arm.maximum_output_tokens
            )
        )
    assert not seen and not broker.snapshot()
