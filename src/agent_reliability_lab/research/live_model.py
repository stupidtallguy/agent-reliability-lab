"""One OpenAI SDK HTTP request per durable permit, with explicit mock isolation."""

import asyncio
import json
import os
import re
import time

import httpx2
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)

from agent_reliability_lab.agent.errors import BudgetExceeded, ModelFailure
from agent_reliability_lab.agent.journal import Redactor
from agent_reliability_lab.agent.models.openai import parse_completion
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research import live
from agent_reliability_lab.research.pilot_contracts import ProviderObservation
from agent_reliability_lab.research.pilot_model import BoundPilotModel, reply_fingerprint


def chat_payload(model, messages, tools, output_limit):
    if any(not isinstance(message.get("content"), (str, type(None))) for message in messages):
        raise ModelFailure("pilot_multimodal_input_unsupported")
    if any(tool.get("type") != "function" for tool in tools):
        raise ModelFailure("pilot_provider_hosted_tool_unsupported")
    payload = dict(
        model=model,
        messages=messages,
        max_completion_tokens=output_limit,
        n=1,
        stream=False,
        store=False,
        service_tier="default",
    )
    if tools:
        payload.update(tools=tools, parallel_tool_calls=False)
    return payload


class _PermitTransport(httpx2.AsyncBaseTransport):
    def __init__(self, broker, attempt, authority, backend):
        self.broker, self.attempt, self.authority, self.backend = (
            broker,
            attempt,
            authority,
            backend,
        )
        self.dispatched = False
        self.gate_error = None

    async def handle_async_request(self, request):
        if self.authority.profile.provider == "groq":
            mock = self.authority.mode == "mock_http" and type(self.backend) is httpx2.MockTransport
            external = (
                self.authority.mode == "groq_free"
                and live.GROQ_FREE_NETWORK_ENABLED
                and type(self.backend) is httpx2.AsyncHTTPTransport
            )
            if not (mock or external):
                raise ModelFailure("groq_external_activation_locked")
            if external:
                scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
                if scheme != "Bearer" or not self.authority.profile.matches_credential(credential):
                    raise ModelFailure("groq_credential_binding_mismatch")
        if (
            self.broker.authorization is None
            or digest(self.authority.model_dump(mode="json"))
            != self.broker.authorization.content_hash
            or self.authority.mode == "mock_http"
            and not isinstance(self.backend, httpx2.MockTransport)
        ):
            raise ModelFailure("pilot_http_authorization_mismatch")
        if request.method != "POST" or str(request.url) != self.authority.profile.endpoint:
            raise ModelFailure("pilot_http_request_differs_from_reservation")
        raw = await request.aread()
        if self.authority.profile.provider == "groq":
            from agent_reliability_lab.research.groq_model import verify_groq_wire

            verify_groq_wire(self.authority.profile, self.attempt, raw)
        elif digest(json.loads(raw)) != self.attempt.wire_hash:
            raise ModelFailure("pilot_http_request_differs_from_reservation")
        if self.authority.mode == "paid_openai" and not live.PUBLIC_PROVIDER_NETWORK_ENABLED:
            raise ModelFailure("pilot_external_activation_locked")
        if self.dispatched:
            raise ModelFailure("pilot_attempt_already_dispatched")
        # Avoid letting the SDK translate a gate failure into an ambiguous network error.
        started = time.monotonic()
        try:
            remaining = self.broker.begin_dispatch(self.attempt)
            if remaining is None:
                raise ModelFailure("pilot_attempt_already_dispatched")
        except (ValueError, BudgetExceeded, ModelFailure) as error:
            self.gate_error = error
            raise
        self.dispatched = True
        remaining -= time.monotonic() - started
        if remaining <= 0:
            raise httpx2.ReadTimeout("pilot dispatch window expired", request=request)
        try:
            async with asyncio.timeout(remaining):
                response = await self.backend.handle_async_request(request)
                await response.aread()
        except TimeoutError:
            raise httpx2.ReadTimeout("pilot dispatch window expired", request=request) from None
        return response

    async def aclose(self):
        await self.backend.aclose()


class LiveHTTPModel(BoundPilotModel):
    def __init__(self, broker, plan, arm, run_ref, model_config, authority, mock_transport=None):
        if plan.mode != "future_live_requested" or model_config.provider != "openai":
            raise ValueError("provider development plan required")
        if (authority.mode == "mock_http") != isinstance(mock_transport, httpx2.MockTransport):
            raise ValueError("mock authorization requires an injected MockTransport")
        if authority.mode == "paid_openai" and (
            mock_transport is not None or not live.PUBLIC_PROVIDER_NETWORK_ENABLED
        ):
            raise live.ActivationBlocked("external_activation_locked")
        super().__init__(broker, plan, arm, run_ref, model_config)
        self.authority, self.mock_transport = authority, mock_transport

    @property
    def is_mock(self):
        return self.authority.mode == "mock_http"

    async def decide_for_request(
        self, execution_id, request_id, messages, tools, turn, max_output_tokens
    ):
        payload = chat_payload(self.plan.model.model_id, messages, tools, max_output_tokens)
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
            backend, credential = self.mock_transport, "offline-sdk-fixture"
        else:
            if not live.PUBLIC_PROVIDER_NETWORK_ENABLED:
                raise ModelFailure("pilot_external_activation_locked")
            credential = os.environ.get("OPENAI_API_KEY")
            if not credential:
                raise ModelFailure("pilot_credential_unavailable")
            backend = httpx2.AsyncHTTPTransport(retries=0, trust_env=False)
        transport = _PermitTransport(self.broker, attempt, self.authority, backend)
        client = httpx2.AsyncClient(transport=transport, trust_env=False, follow_redirects=False)
        started = time.perf_counter()
        async with AsyncOpenAI(
            api_key=credential,
            admin_api_key="",
            organization="",
            project=self.authority.profile.provider_project or "",
            base_url="https://api.openai.com/v1",
            max_retries=0,
            http_client=client,
            _strict_response_validation=True,
        ) as sdk:
            raw = None
            try:
                raw = await sdk.chat.completions.with_raw_response.create(**payload)
                response = raw.parse()
            except (APIStatusError, APIResponseValidationError) as error:
                code = _failure_code(error)
                self._record(attempt, error.response, started, code=code)
                raise ModelFailure(code) from None
            except (APIConnectionError, TimeoutError, asyncio.CancelledError) as error:
                if transport.dispatched:
                    reason = (
                        "dispatch_interrupted"
                        if isinstance(error, asyncio.CancelledError)
                        else _failure_code(error)
                    )
                    self.broker.mark_uncertain(attempt, reason=reason)
                if isinstance(error, asyncio.CancelledError):
                    raise
                if transport.gate_error is not None:
                    raise transport.gate_error from None
                raise ModelFailure(_failure_code(error)) from None
            except (ValueError, TypeError):
                if raw is not None:
                    self._record(attempt, raw.http_response, started, code="invalid_model_response")
                elif transport.dispatched:
                    self.broker.mark_uncertain(attempt, reason="invalid_model_response")
                raise ModelFailure("invalid_model_response") from None
            try:
                if len(response.choices) != 1:
                    raise ModelFailure("invalid_model_response")
                decision = parse_completion(response)
                reply = reply_fingerprint(Redactor().clean(decision.model_dump(mode="json")))
            except (ModelFailure, ValueError, TypeError, AttributeError):
                self._record(attempt, raw.http_response, started, code="invalid_model_response")
                raise ModelFailure("invalid_model_response") from None
            self._record(attempt, raw.http_response, started, reply=reply)
            return decision

    def _record(self, attempt, response, started, *, code=None, reply=None):
        try:
            body = response.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        metering, invalid = _metering(body)
        model = body.get("model")
        request_id = response.headers.get("x-request-id")
        safe_model = _safe_id(model, r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}")
        safe_request_id = _safe_id(request_id, r"[a-zA-Z0-9_.:-]{1,128}")
        invalid = invalid or model != safe_model or request_id != safe_request_id
        error_code = "invalid_provider_usage_or_identity" if invalid else code
        result = self.broker.observe(
            attempt,
            ProviderObservation(
                outcome="failed" if error_code else "completed",
                reported_model=safe_model,
                provider_request_id=safe_request_id,
                response_hash=reply,
                invalid_metering=True if invalid else None,
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                http_status=response.status_code,
                error_code=error_code,
                **metering,
            ),
        )
        if result["state"] == "breached":
            raise ModelFailure("pilot_provider_bound_breach")
        if invalid:
            raise ModelFailure(error_code)


def _safe_id(value, pattern):
    if isinstance(value, str) and re.fullmatch(pattern, value) and Redactor().text(value) == value:
        return value
    return None


def _metering(body):
    """Keep usable observations when a separate field is malformed or unpriced."""
    usage = body.get("usage")
    invalid = usage is not None and not isinstance(usage, dict)
    usage = usage if isinstance(usage, dict) else {}
    prompt = usage.get("prompt_tokens_details")
    completion = usage.get("completion_tokens_details")
    invalid |= any(
        details is not None and not isinstance(details, dict) for details in (prompt, completion)
    )
    prompt = prompt if isinstance(prompt, dict) else {}
    completion = completion if isinstance(completion, dict) else {}
    unpriced = body.get("service_tier") not in (None, "default")
    for fields, supported in (
        (
            usage,
            {
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "prompt_tokens_details",
                "completion_tokens_details",
            },
        ),
        (prompt, {"text_tokens", "cached_tokens", "cache_write_tokens"}),
        (completion, {"text_tokens", "reasoning_tokens"}),
    ):
        # Zeroed modality or prediction counters are harmless defaults.
        unpriced |= any(
            value not in (0, None) for key, value in fields.items() if key not in supported
        )
    selected = {}
    for name, value, ceiling in (
        ("input_tokens", usage.get("prompt_tokens"), 2_000_000_000),
        ("output_tokens", usage.get("completion_tokens"), 2_000_000_000),
        ("cached_input_tokens", prompt.get("cached_tokens"), 2_000_000_000),
        ("cache_write_tokens", prompt.get("cache_write_tokens"), 2_000_000_000),
        ("reported_total_tokens", usage.get("total_tokens"), 4_000_000_000),
    ):
        if value is None:
            continue
        if type(value) is int and 0 <= value <= ceiling:
            selected[name] = value
        else:
            invalid = True
            # An out-of-range nonnegative count still proves the bound was exceeded.
            unpriced |= type(value) is int and value > ceiling
    for fields, allowed in (
        (prompt, ("text_tokens",)),
        (completion, ("text_tokens", "reasoning_tokens")),
    ):
        invalid |= any(
            fields.get(key) is not None and (type(fields[key]) is not int or fields[key] < 0)
            for key in allowed
        )
    return selected | {"unpriced_usage": unpriced}, invalid


def _failure_code(error):
    if isinstance(error, (APITimeoutError, TimeoutError)):
        return "model_timeout"
    if isinstance(error, RateLimitError):
        return "rate_limited"
    if isinstance(error, (AuthenticationError, NotFoundError)):
        return "model_unavailable"
    if isinstance(error, APIResponseValidationError):
        return "invalid_model_response"
    if isinstance(error, APIConnectionError):
        return "provider_unavailable"
    return "provider_error"
