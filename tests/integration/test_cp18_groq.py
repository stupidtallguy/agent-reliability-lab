import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier

import httpx2
import pytest
from test_cp16_http import response_body

from agent_reliability_lab.agent.config import ModelConfig
from agent_reliability_lab.agent.errors import BudgetExceeded, ModelFailure
from agent_reliability_lab.agent.models.fake import ScriptedModel
from agent_reliability_lab.agent.state import Decision
from agent_reliability_lab.evaluation.contracts import ModelPrice, PriceBook
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research import live
from agent_reliability_lab.research.benchmark import starter_draft
from agent_reliability_lab.research.groq_model import GroqHTTPModel, groq_payload
from agent_reliability_lab.research.groq_qualification import qualification_evidence, qualify_groq
from agent_reliability_lab.research.live_contracts import (
    GroqPacing,
    GroqProfile,
    groq_key_commitment,
)
from agent_reliability_lab.research.live_model import _PermitTransport
from agent_reliability_lab.research.persistence import ResearchStore
from agent_reliability_lab.research.pilot import render_pilot, validate_plan, verify_pilot_report
from agent_reliability_lab.research.pilot_budget import PilotBudgetBroker
from agent_reliability_lab.research.pilot_contracts import GROQ_MODEL, CallRequest

pytestmark = pytest.mark.integration
SCENARIO = "multi_step_resolve_task"
FINGERPRINT = "fp_cp18_fixture"


@pytest.fixture
def factory(manager, monkeypatch):
    async def forbidden(*args):
        pytest.fail("Public HTTP transport is forbidden in the CP18 tests")

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPSDESK_TEST_OWNED", "1")
    store = ResearchStore(manager.engine, "cp18_" + uuid.uuid4().hex)
    asyncio.run(store.initialize())
    dataset, parent = starter_draft(repetitions=1)
    store.append(dataset)
    parent_ref = store.append(parent)
    price = ModelPrice(
        provider="groq",
        model_id=GROQ_MODEL,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        provenance="test_fixture_no_provider_charges_observed",
        input_rate=Decimal(0),
        output_rate=Decimal(0),
    )
    pricing = PriceBook(version="cp18-mock", prices=[price])
    profile = GroqProfile(
        input_ceiling=120000, output_ceiling=256, expected_system_fingerprint=FINGERPRINT
    )

    def create(
        identity="groq_pilot",
        *,
        scenario=SCENARIO,
        profile=profile,
        qualification=False,
        mode="mock_http",
    ):
        protocol, plan = live.draft_live(
            store,
            parent_ref,
            identity,
            profile,
            pricing,
            Decimal(0),
            scenario,
            qualification=qualification,
        )
        store.append(protocol)
        plan_ref = store.append(plan)
        authority = live.draft_authorization(
            store, plan_ref, profile, mode, datetime.now(UTC) + timedelta(minutes=15)
        )
        return plan, plan_ref, authority

    return store, parent, create


def _open(store, plan, _plan_ref, authority):
    auth_ref = store.append(authority)
    broker = PilotBudgetBroker(store.engine, store.scope, plan, authorization=auth_ref)
    broker.initialize()
    arm, *remaining = validate_plan(store, plan)
    broker.open(plan, [arm, *remaining])
    messages = [{"role": "user", "content": "CP18 synthetic test"}]
    payload = groq_payload(authority.profile, messages, [], arm.maximum_output_tokens)
    return broker, arm, auth_ref, payload, messages


def _request(plan, arm, auth_ref, payload):
    return CallRequest(
        attempt_id=uuid.uuid4().hex,
        execution_id=uuid.uuid4().hex,
        allocation=arm,
        turn=0,
        model_config_hash=digest(plan.model.model_dump(mode="json")),
        pricing_hash=plan.pricing_hash,
        input_hash=digest([payload["messages"], payload.get("tools", [])]),
        estimated_input_tokens=30,
        maximum_output_tokens=arm.maximum_output_tokens,
        wire_hash=digest(payload),
        authorization_hash=auth_ref.content_hash,
    )


def _response(decision, index=1):
    body = response_body(decision, GROQ_MODEL)
    body.update(system_fingerprint=FINGERPRINT, x_groq={"id": f"req_fixture_{index}"})
    body["usage"].update(queue_time=0.03, prompt_time=0.01, completion_time=0.1, total_time=0.11)
    return body


def test_groq_development_pilot_reconstructs_score_pinned_pairs_and_usage(factory, monkeypatch):
    store, parent, create = factory
    profile = _qualification_profile().model_copy(
        update={"input_ceiling": 7700, "expected_system_fingerprint": FINGERPRINT}
    )
    plan, plan_ref, authority = create(profile=profile)
    reference = store.append(authority)
    monkeypatch.setenv("GROQ_API_KEY", "test_environment_value")
    readonly = ResearchStore(store.engine.execution_options(postgresql_readonly=True), store.scope)
    readiness = live.preflight(readonly, plan_ref, reference)
    assert readiness["status"] == "ready_for_mock_validation"
    assert readiness["checks"]["credential_configured"]
    assert not readiness["checks"]["public_network_enabled"]
    assert readiness["checks"]["rolling_day_call_limit"] == 16
    script = ScriptedModel(ModelConfig(script=parent.scripts[SCENARIO]))
    sent = []
    now = datetime.now(UTC)
    waits = []

    async def sleep(seconds):
        nonlocal now
        waits.append(seconds)
        now += timedelta(seconds=seconds)

    monkeypatch.setattr(PilotBudgetBroker, "_now", staticmethod(lambda connection: now))
    monkeypatch.setattr("agent_reliability_lab.research.live_model.sleep", sleep)

    async def fake(request):
        assert request.method == "POST" and str(request.url) == authority.profile.endpoint
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert set(body) == {
            "model",
            "messages",
            "max_completion_tokens",
            "n",
            "stream",
            "service_tier",
            "reasoning_effort",
            "include_reasoning",
            "tools",
            "parallel_tool_calls",
        }
        assert body["model"] == GROQ_MODEL and body["service_tier"] == "on_demand"
        assert body["max_completion_tokens"] == 256 and body["n"] == 1
        assert body["reasoning_effort"] == "medium" and not body["include_reasoning"]
        assert not body["stream"] and not body["parallel_tool_calls"]
        assert body["tools"] and all(tool["type"] == "function" for tool in body["tools"])
        sent.append(digest(body))
        turn = sum(message["role"] == "assistant" for message in body["messages"])
        decision = await script.decide(body["messages"], body["tools"], turn, 256)
        return httpx2.Response(200, json=_response(decision, len(sent)))

    report_ref = asyncio.run(
        live.run_provider_pilot(store, reference, mock_transport=httpx2.MockTransport(fake))
    )
    report = readonly.get(report_ref)
    doc = verify_pilot_report(readonly, report)
    pairs = doc["benchmark"]["pairs"]
    assert [len(pair["arms"]) for pair in pairs] == [2, 2]
    assert {tuple(pair["order"]) for pair in pairs} == {
        ("baseline", "guarded"),
        ("guarded", "baseline"),
    }
    assert all(pair["comparison"] == "verified" for pair in pairs)
    for pair in pairs:
        for arm in pair["arms"].values():
            assert arm["measurements"]["task_success"]["status"] == "verified_success", arm
    assert len({arm["execution_id"] for arm in doc["arm_inventory"]}) == 4
    assert all(arm["score_pinned_evidence_available"] for arm in doc["arm_inventory"])
    assert doc["interpretation"] == "mock_http"
    assert doc["usage"]["physical_dispatches"] == doc["usage"]["settlements"] == len(sent)
    assert len(sent) <= plan.limits.total_calls == 16
    assert waits and sum(waits) < plan.limits.duration_seconds
    assert Decimal(doc["usage"]["settled_conservative_usd"]) == 0
    assert doc["usage"]["provider_billed_observations"] == 0
    assert doc["financial_verification"]["invoice_status"] == "unverified"
    assert doc["usage"]["reported_input_tokens"]["sum_observed"] == 21 * len(sent)
    observed = [event["body"] for event in doc["provider_events"] if event["kind"] == "settled"]
    assert [row["request"]["wire_hash"] for row in observed] == sent
    assert [row["observation"]["provider_request_id"] for row in observed] == [
        f"req_fixture_{i}" for i in range(1, len(sent) + 1)
    ]
    exports = render_pilot(doc)
    assert all(
        "unverified" in content and "test_environment_value" not in content
        for content in exports.values()
    )
    assert exports == render_pilot(verify_pilot_report(readonly, report))

    _, other_plan, _ = create("other_experiment")
    with pytest.raises(ValueError, match="pin different evidence"):
        verify_pilot_report(readonly, report.model_copy(update={"plan": other_plan}))


@pytest.mark.parametrize(
    ("variant", "error", "state"),
    [
        ("429", "rate_limited", "observed"),
        ("timeout", "model_timeout", "uncertain"),
        ("missing_usage", None, "observed"),
        ("bad_function", "invalid_model_response", "settled"),
        ("unsupported_tool", "unsupported_model_tool", "observed"),
        ("context_limit", "provider_context_limit", "observed"),
        ("cost", "pilot_provider_bound_breach", "breached"),
        ("unknown_usage", "pilot_provider_bound_breach", "breached"),
        ("fallback", "pilot_provider_bound_breach", "breached"),
        ("paid_tier", "pilot_provider_bound_breach", "breached"),
        ("wrong_model", "pilot_provider_bound_breach", "breached"),
        ("backend_changed", "pilot_provider_bound_breach", "breached"),
        ("backend_missing", "pilot_provider_bound_breach", "breached"),
        ("redirect", "provider_redirect_rejected", "observed"),
    ],
)
def test_groq_http_never_retries_or_follows_fallback(factory, monkeypatch, variant, error, state):
    store, _, create = factory
    plan, plan_ref, authority = create()
    broker, arm, auth_ref, payload, messages = _open(store, plan, plan_ref, authority)
    attempt = _request(plan, arm, auth_ref, payload)
    sent = []

    def fake(request):
        sent.append(request)
        if variant == "timeout":
            raise httpx2.ReadTimeout("untrusted provider error", request=request)
        if variant == "429":
            return httpx2.Response(429, headers={"Retry-After": "0"})
        if variant == "redirect":
            return httpx2.Response(307, headers={"Location": "https://paid-route.invalid/"})
        if variant in ("context_limit", "unsupported_tool"):
            code = "context_length_exceeded" if variant == "context_limit" else "tool_use_failed"
            return httpx2.Response(400, json={"error": {"code": code}})
        body = _response(Decision(answer="fixture"))
        if variant == "missing_usage":
            del body["usage"]
        if variant == "bad_function":
            body["choices"][0]["finish_reason"] = "tool_calls"
            body["choices"][0]["message"]["tool_calls"] = [
                {
                    "id": "bad",
                    "type": "function",
                    "function": {"name": "get_task", "arguments": "[]"},
                }
            ]
        if variant == "cost":
            body["billed_usd"] = "0.00001"
        if variant == "unknown_usage":
            body["usage"]["image_tokens"] = 10
        if variant == "fallback":
            body["fallback"] = True
        if variant == "paid_tier":
            body["service_tier"] = "flex"
        if variant == "wrong_model":
            body["model"] = "openai/gpt-oss-120b"
        if variant == "backend_changed":
            body["system_fingerprint"] = "fp_other"
        if variant == "backend_missing":
            del body["system_fingerprint"]
        return httpx2.Response(200, json=body)

    model = GroqHTTPModel(
        broker,
        plan,
        arm,
        plan.protocol,
        ModelConfig(provider="groq", model_id=GROQ_MODEL),
        authority,
        httpx2.MockTransport(fake),
    )
    monkeypatch.setattr(model, "_bound_request", lambda *args, **kwargs: attempt)

    async def run():
        return await model.decide_for_request(
            attempt.execution_id, attempt.attempt_id, messages, [], 0, arm.maximum_output_tokens
        )

    if error is None:
        assert asyncio.run(run()).usage.input_tokens is None
    else:
        with pytest.raises(ModelFailure, match=error):
            asyncio.run(run())
    row = broker.snapshot()[-1]["body"]
    assert len(sent) == 1 and row["state"] == state
    if state != "settled":
        assert row["charged_tokens"] >= row["reserved_tokens"]
    with pytest.raises(ModelFailure, match="pilot_attempt_already_dispatched"):
        asyncio.run(run())
    if variant == "429":
        later = _request(plan, arm, auth_ref, payload)
        broker.reserve(later)
        with pytest.raises(BudgetExceeded, match="groq_provider_rate_limited"):
            broker.begin_dispatch(later)
    assert len(sent) == 1
    assert "untrusted provider error" not in str(broker.snapshot())


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_groq_quota_is_atomic_across_ledgers_and_counts_uncertain_dispatches(factory, isolation):
    store, _, create = factory
    first, second = create("groq_first"), create("groq_second")
    ledger1, arm1, ref1, payload1, _ = _open(store, *first)
    ledger2, arm2, ref2, payload2, _ = _open(store, *second)
    ledger1 = PilotBudgetBroker(
        store.engine.execution_options(isolation_level=isolation),
        store.scope,
        first[0],
        authorization=ref1,
    )
    ledger2 = PilotBudgetBroker(
        store.engine.execution_options(isolation_level=isolation),
        store.scope,
        second[0],
        authorization=ref2,
    )
    for _ in range(15):
        attempt = _request(first[0], arm1, ref1, payload1)
        ledger1.reserve(attempt)
        assert ledger1.begin_dispatch(attempt) > 0
        ledger1.mark_uncertain(attempt)
    last = (_request(first[0], arm1, ref1, payload1), _request(second[0], arm2, ref2, payload2))
    barrier = Barrier(2)

    def compete(ledger, attempt):
        ledger.reserve(attempt)
        barrier.wait(timeout=10)
        try:
            assert ledger.begin_dispatch(attempt) > 0
        except BudgetExceeded as exc:
            assert str(exc) == "groq_rolling_day_calls"
            return "blocked"
        return "dispatched"

    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(compete, ledger, item)
            for ledger, item in zip((ledger1, ledger2), last, strict=True)
        ]
        assert sorted(f.result(timeout=20) for f in futures) == ["blocked", "dispatched"]
    assert (
        sum(event["kind"] == "dispatched" for event in ledger1.snapshot() + ledger2.snapshot())
        == 16
    )
    # A new plan and another worker still cannot acquire a seventeenth daily permit.
    third = create("groq_third")
    ledger3, arm3, ref3, payload3, _ = _open(store, *third)
    extra = _request(third[0], arm3, ref3, payload3)
    ledger3.reserve(extra)
    with pytest.raises(BudgetExceeded, match="groq_rolling_day_calls"):
        ledger3.begin_dispatch(extra)


def test_groq_blocks_direct_http_changed_endpoint_and_future_activation(factory, monkeypatch):
    store, _, create = factory
    plan, plan_ref, authority = create()
    assert live.preflight(store, plan_ref)["status"] == "awaiting_operator_authorization"
    unapproved = PilotBudgetBroker(store.engine, store.scope, plan)
    unapproved.initialize()
    with pytest.raises(live.ActivationBlocked, match="operator_authorization_required"):
        unapproved.open(plan, validate_plan(store, plan))
    with pytest.raises(live.ActivationBlocked, match="existing_development_protocol_required"):
        create("held_out_forbidden", scenario="held_out_private")
    future = authority.model_copy(
        update={
            "mode": "groq_free",
            "profile": authority.profile.model_copy(
                update={
                    "free_organization_evidence": "a" * 64,
                    "free_key_commitment": groq_key_commitment("test_only"),
                }
            ),
        }
    )
    future_ref = store.append(future)
    monkeypatch.setattr(live, "PUBLIC_PROVIDER_NETWORK_ENABLED", True)
    monkeypatch.setenv("GROQ_API_KEY", "test_only")
    assert set(live.preflight(store, plan_ref, future_ref)["issues"]) == {
        "groq_external_activation_locked",
        "groq_account_quota_unverified",
        "groq_live_fingerprint_qualification_required",
    }
    with pytest.raises(live.ActivationBlocked, match="groq_external_activation_locked"):
        asyncio.run(live.run_provider_pilot(store, future_ref, activate_paid=True))

    plan, plan_ref, authority = create("gate_test")
    broker, arm, ref, payload, _ = _open(store, plan, plan_ref, authority)
    attempt = _request(plan, arm, ref, payload)

    def forbidden(_):
        pytest.fail("Pre-dispatch rejection reached mock HTTP")

    permit = _PermitTransport(broker, attempt, authority, httpx2.MockTransport(forbidden))
    for endpoint, error in (
        ("https://router.invalid/openai/v1/chat/completions", "differs_from_reservation"),
        (authority.profile.endpoint, "unknown or conflicting physical provider attempt"),
    ):
        with pytest.raises(
            ValueError if endpoint == authority.profile.endpoint else ModelFailure, match=error
        ):
            asyncio.run(permit.handle_async_request(httpx2.Request("POST", endpoint, json=payload)))
    broker.reserve(attempt)
    altered = payload | {"model": "paid-substitution"}
    with pytest.raises(ModelFailure, match="differs_from_reservation"):
        asyncio.run(
            permit.handle_async_request(
                httpx2.Request("POST", authority.profile.endpoint, json=altered)
            )
        )
    forged = _request(plan, arm, ref, altered)
    broker.reserve(forged)
    forged_permit = _PermitTransport(broker, forged, authority, httpx2.MockTransport(forbidden))
    with pytest.raises(ModelFailure, match="groq_wire_policy_mismatch"):
        asyncio.run(
            forged_permit.handle_async_request(
                httpx2.Request("POST", authority.profile.endpoint, json=altered)
            )
        )
    duplicate_fields = b'{"model":"paid-substitution",' + json.dumps(payload).encode()[1:]
    with pytest.raises(ModelFailure, match="groq_wire_policy_mismatch"):
        asyncio.run(
            permit.handle_async_request(
                httpx2.Request("POST", authority.profile.endpoint, content=duplicate_fields)
            )
        )
    assert all(event["kind"] == "reserved" for event in broker.snapshot())


def test_future_free_transport_sends_only_one_approved_request_with_network_replaced(
    factory, monkeypatch
):
    store, _, create = factory
    profile = _qualification_profile()
    _, qualification_plan, qualification = create(
        "qualify_free", profile=profile, qualification=True
    )
    qualification = live.draft_authorization(
        store, qualification_plan, profile, "groq_free", qualification.deadline
    )
    qualification_ref = store.append(qualification)
    sent = []

    async def intercept(_, request):
        sent.append(request)
        assert request.headers["authorization"] == "Bearer fixture_only"
        assert request.url == profile.endpoint
        if len(sent) == 1:
            return httpx2.Response(200, json=_response(Decision(answer="OK")))
        return httpx2.Response(429, headers={"Retry-After": "0"})

    # Replace the network handler before exercising the dormant release branch.
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", intercept)
    monkeypatch.setattr(live, "GROQ_FREE_NETWORK_ENABLED", True)
    monkeypatch.setenv("GROQ_API_KEY", "fixture_only")
    result = asyncio.run(qualify_groq(store, qualification_ref, activate_free=True))
    assert result["qualified"] and result["dispatches"] == 1
    profile = profile.model_copy(
        update={
            "input_ceiling": 7000,
            "expected_system_fingerprint": FINGERPRINT,
            "fingerprint_qualification": qualification_ref,
            "qualification_event_hash": result["event_hash"],
        }
    )
    plan, plan_ref, authority = create(profile=profile, mode="groq_free")
    auth_ref = store.append(authority)
    monkeypatch.setenv("GROQ_API_KEY", "different_account_fixture")
    assert live.preflight(store, plan_ref, auth_ref)["issues"] == [
        "free_credential_binding_mismatch"
    ]
    monkeypatch.setenv("GROQ_API_KEY", "fixture_only")
    with pytest.raises(live.ActivationBlocked, match="explicit_free_activation_required"):
        asyncio.run(live.run_provider_pilot(store, auth_ref, activate_paid=True))
    assert len(sent) == 1

    _, make_model = live.open_provider_pilot(
        store, plan_ref, plan.protocol, auth_ref, None, False, True
    )
    arm = validate_plan(store, plan)[0]
    model = make_model(
        plan.protocol, arm.slot, arm.arm, ModelConfig(provider="groq", model_id=GROQ_MODEL)
    )
    messages = [{"role": "user", "content": "fixture"}]
    payload = groq_payload(authority.profile, messages, [], arm.maximum_output_tokens)
    attempt = _request(plan, arm, auth_ref, payload)
    monkeypatch.setattr(model, "_bound_request", lambda *args, **kwargs: attempt)
    monkeypatch.setenv("GROQ_API_KEY", "different_account_fixture")
    with pytest.raises(ModelFailure, match="groq_credential_binding_mismatch"):
        asyncio.run(
            model.decide_for_request(
                attempt.execution_id, attempt.attempt_id, messages, [], 0, arm.maximum_output_tokens
            )
        )
    assert len(sent) == 1
    monkeypatch.setenv("GROQ_API_KEY", "fixture_only")
    with pytest.raises(ModelFailure, match="rate_limited"):
        asyncio.run(
            model.decide_for_request(
                attempt.execution_id, attempt.attempt_id, messages, [], 0, arm.maximum_output_tokens
            )
        )
    assert len(sent) == 2 and digest(json.loads(sent[1].content)) == attempt.wire_hash
    row = model.broker.snapshot()[-1]["body"]
    assert row["quota"] == "groq-free"
    assert row["state"] == "observed"
    assert row["observation"]["groq_rate_limits"] == {"retry-after": 0}
    assert "fixture_only" not in str(model.broker.snapshot())


def _qualification_profile():
    return GroqProfile(
        input_ceiling=256,
        output_ceiling=256,
        free_organization_evidence="a" * 64,
        free_key_commitment=groq_key_commitment("fixture_only"),
        pacing=GroqPacing(
            requests_per_minute=30,
            requests_per_day=1000,
            tokens_per_minute=8000,
            tokens_per_day=200000,
        ),
    )


@pytest.mark.parametrize(
    "variant", ["ok", "missing_fingerprint", "wrong_model", "timeout", "429", "missing_account"]
)
def test_groq_qualification_records_only_one_permit_and_never_becomes_a_trial(factory, variant):
    store, _, create = factory
    profile = _qualification_profile()
    if variant == "missing_account":
        profile = profile.model_copy(update={"free_organization_evidence": None})
    _, plan_ref, auth = create("qualification", profile=profile, qualification=True)
    ref = store.append(auth)
    sent = []

    async def intercept(request):
        sent.append(request)
        body = json.loads(request.content)
        assert body["model"] == GROQ_MODEL
        assert body["messages"] == [{"role": "user", "content": "Reply with OK."}]
        assert "tools" not in body and "authorization" not in request.headers
        if variant == "timeout":
            raise httpx2.ReadTimeout("fixture")
        if variant == "429":
            return httpx2.Response(429, headers={"Retry-After": "5"})
        result = _response(Decision(answer="OK"))
        if variant == "missing_fingerprint":
            del result["system_fingerprint"]
        if variant == "wrong_model":
            result["model"] = "wrong"
        return httpx2.Response(200, json=result)

    transport = httpx2.MockTransport(intercept)
    if variant == "missing_account":
        with pytest.raises(live.ActivationBlocked, match="free_organization_unverified"):
            asyncio.run(qualify_groq(store, ref, mock_transport=transport))
        assert not sent
        return
    with pytest.raises(live.ActivationBlocked, match="provider_pilot_protocol_mismatch"):
        asyncio.run(live.run_provider_pilot(store, ref, mock_transport=transport))
    result = asyncio.run(qualify_groq(store, ref, mock_transport=transport))
    assert len(sent) == result["dispatches"] == 1
    assert qualification_evidence(store, ref) == result
    assert result["mode"] == "mock_http"
    assert result["qualified"] == (variant == "ok")
    if variant == "timeout":
        assert result["state"] == "uncertain" and result["observation"] is None
    if variant == "429":
        assert result["observation"]["groq_rate_limits"] == {"retry-after": 5}
    with pytest.raises(live.ActivationBlocked, match="pilot_ledger_already_opened"):
        asyncio.run(qualify_groq(store, ref, mock_transport=transport))
    assert len(sent) == 1
    assert not store.list("benchmark_run")
    if variant == "ok":
        profile = profile.model_copy(
            update={
                "expected_system_fingerprint": FINGERPRINT,
                "fingerprint_qualification": ref,
                "qualification_event_hash": result["event_hash"],
            }
        )
        _, pilot_ref, mock_pilot = create("separate_study", profile=profile)
        assert store.append(mock_pilot)
        with pytest.raises(live.ActivationBlocked, match="groq_fingerprint_evidence_mismatch"):
            live.draft_authorization(store, pilot_ref, profile, "groq_free", mock_pilot.deadline)
        with pytest.raises(live.ActivationBlocked, match="groq_fingerprint_evidence_mismatch"):
            live.draft_authorization(
                store,
                pilot_ref,
                profile.model_copy(update={"expected_system_fingerprint": "fp_changed"}),
                "mock_http",
                mock_pilot.deadline,
            )


@pytest.mark.parametrize("revoked", [False, True])
def test_groq_token_pacing_rechecks_authorization_before_sending(factory, monkeypatch, revoked):
    store, _, create = factory
    profile = _qualification_profile().model_copy(
        update={"input_ceiling": 4500, "expected_system_fingerprint": FINGERPRINT}
    )
    first = create("paced_first", profile=profile)
    second = create("paced_second", profile=profile)
    ledger1, arm1, ref1, payload1, _ = _open(store, *first)
    ledger2, arm2, ref2, payload2, _ = _open(store, *second)
    now = datetime.now(UTC)
    monkeypatch.setattr(PilotBudgetBroker, "_now", staticmethod(lambda connection: now))
    prior = _request(first[0], arm1, ref1, payload1)
    ledger1.reserve(prior)
    ledger1.begin_dispatch(prior)
    ledger1.mark_uncertain(prior)
    next_request = _request(second[0], arm2, ref2, payload2)
    ledger2.reserve(next_request)
    sent, waits = [], []

    async def sleep(seconds):
        nonlocal now
        waits.append(seconds)
        if revoked:
            store.append(
                second[2].model_copy(
                    update={
                        "version": 2,
                        "supersedes": ref2,
                        "decision": "revoked",
                    }
                )
            )
        now += timedelta(seconds=seconds)

    async def intercept(request):
        sent.append(request)
        return httpx2.Response(200)

    monkeypatch.setattr("agent_reliability_lab.research.live_model.sleep", sleep)
    transport = _PermitTransport(ledger2, next_request, second[2], httpx2.MockTransport(intercept))
    http_request = httpx2.Request("POST", profile.endpoint, json=payload2)
    if revoked:
        with pytest.raises(live.ActivationBlocked, match="authorization_missing_or_superseded"):
            asyncio.run(transport.handle_async_request(http_request))
        assert not sent
        assert ledger2.snapshot()[-1]["kind"] == "reserved"
    else:
        assert asyncio.run(transport.handle_async_request(http_request)).status_code == 200
        assert len(sent) == 1 and ledger2.snapshot()[-1]["kind"] == "dispatched"
    assert waits == [60.0]
