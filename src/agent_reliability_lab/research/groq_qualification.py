"""One separately authorized Groq request outside the experimental sample."""

import sqlalchemy as sa

from agent_reliability_lab.agent.errors import BudgetExceeded, ModelFailure
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research import live
from agent_reliability_lab.research.groq_model import (
    groq_payload,
    qualification_messages,
    submit_groq,
)
from agent_reliability_lab.research.pilot import validate_plan
from agent_reliability_lab.research.pilot_budget import PilotBudgetBroker, ledgers
from agent_reliability_lab.research.pilot_contracts import CallRequest


def _binding(store, reference):
    authority = store.get(reference)
    if authority.kind != "benchmark_live_authorization" or authority.purpose != "groq_fingerprint":
        raise live.ActivationBlocked("groq_qualification_authorization_required")
    plan = store.get(authority.pilot)
    live.validate_authorization(store, authority, plan)
    arms = validate_plan(store, plan)
    messages = qualification_messages()
    payload = groq_payload(authority.profile, messages, [], plan.limits.maximum_output_tokens)
    request = CallRequest(
        attempt_id=plan.ledger_id,
        execution_id=plan.ledger_id,
        allocation=arms[0],
        turn=0,
        model_config_hash=authority.configuration_hash,
        pricing_hash=authority.pricing_hash,
        input_hash=digest([messages, []]),
        estimated_input_tokens=len(messages[0]["content"].encode("utf-8")),
        maximum_output_tokens=plan.limits.maximum_output_tokens,
        wire_hash=digest(payload),
        authorization_hash=reference.content_hash,
    )
    return (
        authority,
        plan,
        PilotBudgetBroker(store.engine, store.scope, plan, authorization=reference),
        request,
        payload,
    )


def qualification_evidence(store, reference):
    authority, plan, broker, request, _ = _binding(store, reference)
    with store.engine.connect() as connection:
        initialized = connection.scalar(sa.select(sa.func.to_regclass("opsdesk_pilot.ledgers")))
        present = initialized and connection.scalar(
            sa.select(ledgers.c.ledger_id).where(ledgers.c.ledger_id == plan.ledger_id)
        )
    events = broker.snapshot() if present else []
    if (
        any(
            event["attempt_id"] != request.attempt_id
            or event["body"]["request"] != request.model_dump(mode="json")
            for event in events
        )
        or sum(event["kind"] == "dispatched" for event in events) > 1
    ):
        raise live.ActivationBlocked("groq_qualification_event_mismatch")
    body = events[-1]["body"] if events else {}
    observation = body.get("observation")
    qualified = (
        body.get("state") == "settled"
        and observation is not None
        and observation["outcome"] == "completed"
        and observation["reported_model"] == authority.profile.returned_model
        and observation.get("system_fingerprint") is not None
        and observation["provider_request_id"] is not None
    )
    return {
        "schema": "groq-fingerprint-qualification-1.0.0",
        "authorization": reference.model_dump(mode="json"),
        "mode": authority.mode,
        "state": body.get("state", "not_dispatched"),
        "qualified": qualified,
        "event_hash": digest(events),
        "dispatches": sum(event["kind"] == "dispatched" for event in events),
        "dispatched_at": next(
            (event["recorded_at"] for event in events if event["kind"] == "dispatched"), None
        ),
        "observation": observation,
        "uncertain_reason": body.get("uncertain_reason"),
        "local_held_tokens": body.get("charged_tokens"),
        "provider_invoice_verified": False,
    }


def verify_qualification_pin(store, authority):
    profile = authority.profile
    if authority.purpose is not None:
        raise live.ActivationBlocked("groq_qualification_cannot_reuse_evidence")
    reference = profile.fingerprint_qualification
    source = store.get(reference)
    evidence = qualification_evidence(store, reference)
    if (
        authority.mode != source.mode
        or source.pilot == authority.pilot
        or not evidence["qualified"]
        or evidence["event_hash"] != profile.qualification_event_hash
        or evidence["observation"]["system_fingerprint"] != profile.expected_system_fingerprint
        or source.profile.free_organization_evidence != profile.free_organization_evidence
        or source.profile.free_key_commitment != profile.free_key_commitment
        or source.profile.pacing != profile.pacing
    ):
        raise live.ActivationBlocked("groq_fingerprint_evidence_mismatch")


async def qualify_groq(store, reference, *, activate_free=False, mock_transport=None):
    live.require_disposable(store)
    authority, plan, broker, request, payload = _binding(store, reference)
    if authority.mode == "mock_http":
        if activate_free or mock_transport is None:
            raise live.ActivationBlocked("offline_mock_transport_required")
    elif not live.GROQ_FREE_NETWORK_ENABLED:
        raise live.ActivationBlocked("groq_external_activation_locked")
    elif not activate_free or mock_transport is not None:
        raise live.ActivationBlocked("explicit_free_activation_required")
    readiness = live.preflight(store, authority.pilot, reference)
    if readiness["status"] not in {"ready_for_mock_validation", "live_ready"}:
        raise live.ActivationBlocked(readiness["issues"][0])
    broker.initialize()
    broker.open(plan, [request.allocation])
    try:
        await submit_groq(broker, authority, mock_transport, request, payload)
    except (ModelFailure, BudgetExceeded):
        # A physical failure is part of the qualification evidence. Read it without resending.
        evidence = qualification_evidence(store, reference)
        if evidence["dispatches"]:
            return evidence
        raise
    return qualification_evidence(store, reference)
