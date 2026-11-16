"""Groq on-demand Chat Completions through the existing single-use HTTP permit."""

import asyncio
import json
import math
import os
import time

import httpx2
from openai.types.chat import ChatCompletion

from agent_reliability_lab.agent.errors import ModelFailure
from agent_reliability_lab.agent.journal import Redactor
from agent_reliability_lab.agent.models.openai import parse_completion
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research import live
from agent_reliability_lab.research.live_contracts import GroqProfile
from agent_reliability_lab.research.live_model import (
    _metering,
    _PermitTransport,
    _safe_id,
    chat_payload,
)
from agent_reliability_lab.research.pilot_contracts import ProviderObservation
from agent_reliability_lab.research.pilot_model import BoundPilotModel, reply_fingerprint

_TIMINGS = {"queue_time", "prompt_time", "completion_time", "total_time"}


def groq_payload(profile, messages, tools, output_limit):
    if any("name" in message for message in messages):
        raise ModelFailure("groq_unsupported_message_name")
    payload = chat_payload(profile.requested_model, messages, tools, output_limit)
    # Chat Completions on Groq does not support OpenAI's store parameter.
    del payload["store"]
    payload.update(
        service_tier=profile.service_tier,
        reasoning_effort=profile.reasoning_effort,
        include_reasoning=profile.include_reasoning,
    )
    return payload


def _groq_metering(body):
    usage = body.get("usage")
    timings_valid = True
    if isinstance(usage, dict):
        timings_valid = all(
            type(value) in (int, float) and 0 <= value < math.inf
            for key, value in usage.items()
            if key in _TIMINGS and value is not None
        )
        usage = {key: value for key, value in usage.items() if key not in _TIMINGS}
    metering, invalid = _metering({"usage": usage})
    if any(body.get(key) is not None for key in ("cost", "billed_usd", "usage_breakdown")):
        metering["unpriced_usage"] = True
    return metering, invalid or not timings_valid


def _failure_code(response, body):
    if response.is_success:
        return None
    if response.status_code == 429:
        return "rate_limited"
    if response.status_code in (401, 403, 404):
        return "model_unavailable"
    if response.is_redirect:
        return "provider_redirect_rejected"
    error = body.get("error")
    if response.status_code == 400 and isinstance(error, dict):
        if error.get("code") == "context_length_exceeded":
            return "provider_context_limit"
        if error.get("code") == "tool_use_failed":
            return "unsupported_model_tool"
    return "provider_error"


def _parse_reply(body, request_id):
    response = ChatCompletion.model_validate(body)
    if len(response.choices) != 1:
        raise ModelFailure("invalid_model_response")
    decision = parse_completion(response)
    if (
        len(decision.calls) > 1
        or (response.choices[0].finish_reason == "tool_calls") != bool(decision.calls)
        or any(not isinstance(json.loads(call.arguments_json), dict) for call in decision.calls)
    ):
        raise ModelFailure("invalid_model_response")
    return decision.model_copy(update={"provider_request_id": request_id})


class GroqHTTPModel(BoundPilotModel):
    def __init__(self, broker, plan, arm, run_ref, model_config, authority, mock_transport):
        if (
            not isinstance(authority.profile, GroqProfile)
            or plan.model.provider != "groq"
            or model_config.provider != "groq"
        ):
            raise live.ActivationBlocked("groq_brokered_development_plan_required")
        if authority.mode == "mock_http":
            if type(mock_transport) is not httpx2.MockTransport:
                raise live.ActivationBlocked("offline_mock_transport_required")
        elif not live.GROQ_FREE_NETWORK_ENABLED or mock_transport is not None:
            raise live.ActivationBlocked("groq_external_activation_locked")
        super().__init__(broker, plan, arm, run_ref, model_config)
        self.authority, self.mock_transport = authority, mock_transport

    @property
    def is_mock(self):
        return self.authority.mode == "mock_http"

    async def decide_for_request(
        self, execution_id, request_id, messages, tools, turn, max_output_tokens
    ):
        profile = self.authority.profile
        payload = groq_payload(profile, messages, tools, max_output_tokens)
        attempt = self._bound_request(
            execution_id,
            request_id,
            messages,
            tools,
            turn,
            max_output_tokens,
            authorization_hash=self.broker.authorization.content_hash,
            wire_hash=digest(payload),
        )
        self.broker.reserve(attempt)
        if self.is_mock:
            headers, backend = {}, self.mock_transport
        else:
            if not live.GROQ_FREE_NETWORK_ENABLED:
                raise ModelFailure("groq_external_activation_locked")
            credential = os.environ.get("GROQ_API_KEY", "").strip()
            if not credential:
                raise ModelFailure("pilot_credential_unavailable")
            if not profile.matches_credential(credential):
                raise ModelFailure("groq_credential_binding_mismatch")
            headers = {"Authorization": "Bearer " + credential}
            backend = httpx2.AsyncHTTPTransport(retries=0, trust_env=False)
        transport = _PermitTransport(self.broker, attempt, self.authority, backend)
        started = time.perf_counter()
        async with httpx2.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False
        ) as client:
            try:
                response = await client.post(profile.endpoint, json=payload, headers=headers)
            except (httpx2.RequestError, asyncio.CancelledError) as error:
                code = "provider_unavailable"
                if isinstance(error, httpx2.TimeoutException):
                    code = "model_timeout"
                if isinstance(error, asyncio.CancelledError):
                    code = "dispatch_interrupted"
                if transport.dispatched:
                    self.broker.mark_uncertain(attempt, reason=code)
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise ModelFailure(code) from None
        return self._record(attempt, response, started)

    def _record(self, attempt, response, started):
        try:
            body = response.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        profile = self.authority.profile
        meta = body.get("x_groq")
        raw_id = meta.get("id") if isinstance(meta, dict) else response.headers.get("x-request-id")
        request_id = _safe_id(raw_id, r"[a-zA-Z0-9_.:-]{1,128}")
        model = _safe_id(body.get("model"), r"[a-zA-Z0-9][a-zA-Z0-9_./:-]{0,127}")
        fingerprint = _safe_id(body.get("system_fingerprint"), r"[a-zA-Z0-9_.:-]{1,128}")
        route_mismatch = (
            body.get("service_tier") not in (None, profile.service_tier, "default")
            or body.get("provider") not in (None, profile.provider)
            or body.get("fallback") not in (None, False)
            or body.get("model") not in (None, profile.returned_model)
            or (response.is_success or "system_fingerprint" in body)
            and fingerprint != profile.expected_system_fingerprint
        )
        usage, invalid = _groq_metering(body)
        code = _failure_code(response, body)
        if route_mismatch:
            code = "groq_route_mismatch"
        elif invalid or (response.is_success and (request_id is None or model is None)):
            code = "invalid_provider_usage_or_identity"
            invalid = True
        decision, reply = None, None
        if code is None:
            try:
                decision = _parse_reply(body, request_id)
                reply = reply_fingerprint(Redactor().clean(decision.model_dump(mode="json")))
            except (ModelFailure, ValueError, TypeError, AttributeError) as error:
                code = str(error) if isinstance(error, ModelFailure) else "invalid_model_response"
        recorded = self.broker.observe(
            attempt,
            ProviderObservation(
                outcome="failed" if code or usage["unpriced_usage"] else "completed",
                error_code=code,
                reported_model=model,
                provider_request_id=request_id,
                response_hash=reply,
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                http_status=response.status_code,
                system_fingerprint=fingerprint,
                route_mismatch=True if route_mismatch else None,
                invalid_metering=True if invalid else None,
                **usage,
            ),
        )
        if recorded["state"] == "breached":
            raise ModelFailure("pilot_provider_bound_breach")
        if code:
            raise ModelFailure(code)
        return decision
