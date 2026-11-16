"""One OpenAI SDK HTTP request per durable permit, with explicit mock isolation."""

import asyncio
import json
import os
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
        if (
            self.broker.authorization is None
            or digest(self.authority.model_dump(mode="json"))
            != self.broker.authorization.content_hash
            or self.authority.mode == "mock_http"
            and not isinstance(self.backend, httpx2.MockTransport)
        ):
            raise ModelFailure("pilot_http_authorization_mismatch")
        if (
            request.method != "POST"
            or str(request.url) != self.authority.profile.endpoint
            or digest(json.loads(await request.aread())) != self.attempt.wire_hash
        ):
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
        usage = body.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        details = usage.get("prompt_tokens_details")
        details = details if isinstance(details, dict) else {}
        output_details = usage.get("completion_tokens_details")
        output_details = output_details if isinstance(output_details, dict) else {}
        explicit_unpriced_usage = (
            body.get("service_tier") not in (None, "default")
            or details.get("audio_tokens") not in (None, 0)
            or output_details.get("audio_tokens") not in (None, 0)
        )
        try:
            observation = ProviderObservation(
                outcome="failed" if code else "completed",
                reported_model=body.get("model"),
                provider_request_id=response.headers.get("x-request-id"),
                response_hash=reply,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                cached_input_tokens=details.get("cached_tokens"),
                cache_write_tokens=details.get("cache_write_tokens"),
                reported_total_tokens=usage.get("total_tokens"),
                unpriced_usage=explicit_unpriced_usage,
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                http_status=response.status_code,
                error_code=code,
            )
            result = self.broker.observe(attempt, observation)
        except ValueError:
            self.broker.mark_uncertain(attempt, reason="invalid_provider_usage_or_identity")
            raise ModelFailure("invalid_provider_usage_or_identity") from None
        if result["state"] == "breached":
            raise ModelFailure("pilot_provider_bound_breach")


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
