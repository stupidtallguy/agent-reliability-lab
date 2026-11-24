"""Native loopback-only Ollama transport for sealed development requests."""

import asyncio
import json
import re
import tempfile
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

import httpx2

from agent_reliability_lab.agent.errors import ModelFailure
from agent_reliability_lab.agent.journal import Redactor
from agent_reliability_lab.agent.state import Decision, ModelCall, Usage
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.pilot_contracts import OllamaProfile, ProviderObservation
from agent_reliability_lab.research.pilot_model import BoundPilotModel, reply_fingerprint

ENDPOINT = "http://127.0.0.1:11434"
TAG = "qwen3.5:4b"
DURATIONS = ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")


def client(transport=None):
    if transport is not None and type(transport) is not httpx2.MockTransport:
        raise ValueError("only an in-memory HTTP mock can replace the loopback transport")
    return httpx2.AsyncClient(
        base_url=ENDPOINT,
        transport=transport,
        trust_env=False,
        follow_redirects=False,
        timeout=90.0,
    )


async def identity(http, hardware, *, smoke=False, profile_version="local-ollama-1"):
    """Metadata only. A remote/cloud-backed tag has no eligible local weights."""
    tags = (await http.get("/api/tags")).raise_for_status().json()["models"]
    matches = [x for x in tags if x["name"] == TAG and x.get("model") == TAG]
    if len(matches) != 1:
        raise ModelFailure("ollama_model_unavailable")
    item = matches[0]
    show = (await http.post("/api/show", json={"model": TAG})).raise_for_status().json()
    version = (await http.get("/api/version")).raise_for_status().json()["version"]
    details = show["details"]
    if (
        any(x.get(k) for x in (item, show) for k in ("remote_model", "remote_host"))
        or details.get("format") != "gguf"
        or details.get("family") != "qwen35"
        or "tools" not in show.get("capabilities", [])
        or not show.get("template")
        or not re.fullmatch("[0-9a-f]{64}", item.get("digest", ""))
    ):
        raise ModelFailure("ollama_local_identity_unverified")
    return OllamaProfile(
        version=profile_version,
        model_digest=item["digest"],
        runtime=version,
        quantization=details["quantization_level"],
        template_hash=digest(show["template"]),
        hardware=hardware,
        smoke=smoke,
    )


def discovery_tools(tools):
    """Inline the task patch that Ollama 0.40.16 omits when presented as a reference."""
    output = []
    for tool in tools:
        function = tool["function"]
        if function["name"] == "update_task":
            schema = function["parameters"]
            props = schema["properties"]
            if props["patch"] != {"$ref": "#/$defs/TaskPatch"} or set(schema["$defs"]) != {
                "TaskPatch"
            }:
                raise ModelFailure("ollama_discovery_unexpected_patch_schema")
            expanded = {key: value for key, value in schema.items() if key != "$defs"}
            expanded["properties"] = props | {"patch": schema["$defs"]["TaskPatch"]}
            tool = tool | {"function": function | {"parameters": expanded}}
        output.append(tool)
    return output


def payload(profile, messages, tools):
    native, names = [], {}
    for original in messages:
        msg = dict(original)
        if msg["role"] == "assistant":
            msg["content"] = msg.get("content") or ""
            calls = []
            for call in msg.get("tool_calls", []):
                name = call["function"]["name"]
                names[call["id"]] = name
                calls.append(
                    {
                        "id": call["id"],
                        "function": {
                            "name": name,
                            "arguments": json.loads(call["function"]["arguments"]),
                        },
                    }
                )
            msg["tool_calls"] = calls
        elif msg["role"] == "tool":
            msg["tool_name"] = names[msg["tool_call_id"]]
        native.append(msg)
    return dict(
        model=profile.tag,
        messages=native,
        tools=discovery_tools(tools) if profile.uses_discovery else tools,
        stream=False,
        think=False,
        truncate=False,
        shift=False,
        options=dict(
            num_ctx=profile.num_ctx,
            num_predict=profile.num_predict,
            temperature=profile.temperature,
            seed=profile.seed,
        ),
    )


def count(body, key):
    value = body.get(key)
    if value is not None and (type(value) is not int or value < 0):
        raise ModelFailure("ollama_invalid_metering")
    return value


def parse_reply(body, request_id):
    if body.get("model") != TAG:
        raise ModelFailure("ollama_returned_model_mismatch")
    if body.get("done") is not True or body.get("done_reason") != "stop":
        raise ModelFailure("ollama_incomplete_output")
    msg = body["message"]
    if msg.get("role") != "assistant" or not isinstance(msg.get("content"), str):
        raise ModelFailure("ollama_invalid_message")
    calls = []
    for i, item in enumerate(msg.get("tool_calls", [])):
        function = item["function"]
        if (
            not isinstance(function.get("name"), str)
            or not function["name"]
            or not isinstance(function["arguments"], dict)
        ):
            raise ModelFailure("ollama_invalid_tool_call")
        # Ollama versions may omit IDs. Keep synthesized IDs physical-request scoped.
        calls.append(
            ModelCall(
                call_id=item.get("id") or f"{request_id}_{i}",
                name=function["name"],
                arguments_json=json.dumps(
                    function["arguments"], allow_nan=False, ensure_ascii=False
                ),
            )
        )
    if len({call.call_id for call in calls}) != len(calls) or not (calls or msg["content"].strip()):
        raise ModelFailure("ollama_invalid_message")
    inp, out = count(body, "prompt_eval_count"), count(body, "eval_count")
    if (inp or 0) + (out or 0) > 4096 or (out or 0) > 256:
        raise ModelFailure("ollama_context_or_output_exceeded")
    return Decision(
        answer=msg["content"],
        calls=calls,
        reported_model=TAG,
        usage=Usage(
            input_tokens=inp,
            output_tokens=out,
            source="provider" if inp is not None or out is not None else "unavailable",
        ),
    )


@contextmanager
def inference_slot():
    """Nonblocking per-host/user lock, released by the OS after a process exit."""
    import os

    with (Path(tempfile.gettempdir()) / "opsdesk-ollama-11434.lock").open("a+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ModelFailure("ollama_busy") from None
        yield


class OllamaModel(BoundPilotModel):
    def __init__(self, broker, plan, arm, run_ref, config, transport=None):
        super().__init__(broker, plan, arm, run_ref, config)
        self.is_mock = type(transport) is httpx2.MockTransport
        if (
            plan.mode != ("ollama_mock" if self.is_mock else "ollama_local")
            or plan.model.provider != "ollama"
            or not broker.local_opt_in
        ):
            raise ValueError("local transport differs from the opted-in plan")
        self.transport = transport

    async def decide_for_request(
        self, execution_id, request_id, messages, tools, turn, max_output_tokens
    ):
        profile = self.plan.model.local_profile
        wire = payload(profile, messages, tools)
        request = self._bound_request(
            execution_id,
            request_id,
            messages,
            tools,
            turn,
            max_output_tokens,
            authorization_hash=self.broker.plan_hash,
            wire_hash=digest(wire),
        )
        # Reserve the full native context. UTF-8 wire bytes are not tokenizer observations.
        request = request.model_copy(update={"estimated_input_tokens": None})
        # Only the exact in-memory transport bypasses the real endpoint's machine lock.
        with nullcontext() if self.is_mock else inference_slot():
            async with client(self.transport) as http:
                try:
                    observed_profile = await identity(
                        http, profile.hardware, smoke=profile.smoke, profile_version=profile.version
                    )
                except (httpx2.HTTPError, ValueError, KeyError, TypeError):
                    raise ModelFailure("ollama_identity_observation_unavailable") from None
                if observed_profile != profile:
                    raise ModelFailure("ollama_identity_changed")
                self.broker.reserve(request)
                remaining = self.broker.begin_dispatch(request)
                if remaining is None:
                    raise ModelFailure("pilot_attempt_already_dispatched")
                started = time.perf_counter()
                try:
                    async with asyncio.timeout(min(90, remaining)):
                        response = await http.post("/api/chat", json=wire)
                except (httpx2.RequestError, TimeoutError, asyncio.CancelledError) as exc:
                    self.broker.mark_uncertain(request, reason="ollama_transport_interrupted")
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    code = (
                        "ollama_timeout"
                        if isinstance(exc, (TimeoutError, httpx2.TimeoutException))
                        else "ollama_connection_error"
                    )
                    raise ModelFailure(code) from None
                elapsed = round(1000 * (time.perf_counter() - started))
                observed = dict(elapsed_ms=elapsed, http_status=response.status_code)
                try:
                    if response.is_redirect:
                        raise ModelFailure("ollama_redirect_rejected")
                    body = response.json()
                    if not response.is_success or "error" in body:
                        message = str(body.get("error", "")).lower()
                        raise ModelFailure(
                            "ollama_context_overflow"
                            if "context" in message
                            else "ollama_response_error"
                        )
                    observed.update(
                        input_tokens=count(body, "prompt_eval_count"),
                        output_tokens=count(body, "eval_count"),
                        reported_model=TAG if body.get("model") == TAG else None,
                        ollama_duration_ns={
                            k: count(body, k) for k in DURATIONS if body.get(k) is not None
                        },
                    )
                    decision = parse_reply(body, request_id)
                    reply_hash = reply_fingerprint(
                        Redactor().clean(decision.model_dump(mode="json"))
                    )
                except (ValueError, TypeError, KeyError, AttributeError, ModelFailure) as exc:
                    code = exc.code if isinstance(exc, ModelFailure) else "ollama_invalid_response"
                    self.broker.observe(
                        request, ProviderObservation(outcome="failed", error_code=code, **observed)
                    )
                    raise ModelFailure(code) from None
                settled = self.broker.observe(
                    request,
                    ProviderObservation(outcome="completed", response_hash=reply_hash, **observed),
                )
                if settled["state"] == "breached":
                    raise ModelFailure("ollama_bound_breach")
                return decision
