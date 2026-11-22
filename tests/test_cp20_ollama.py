import asyncio

import pytest
from pydantic import ValidationError

from agent_reliability_lab.agent.errors import ModelFailure
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.ollama_model import (
    TAG,
    client,
    inference_slot,
    parse_reply,
    payload,
)
from agent_reliability_lab.research.pilot_contracts import OllamaProfile


def profile(**kw):
    return OllamaProfile(
        model_digest="a" * 64,
        template_hash=digest("template"),
        quantization="Q4_K_M",
        hardware={},
        **kw,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434",
        "https://ollama.com",
        "http://127.0.0.1:11435",
        "http://127.0.0.1:11434@evil.test",
    ],
)
def test_endpoint_is_exact(url):
    with pytest.raises(ValidationError):
        profile(endpoint=url)


def test_exclusive_slot():
    with inference_slot(), pytest.raises(ModelFailure, match="busy"), inference_slot():
        pytest.fail("second caller acquired an active inference slot")


def test_proxy_disabled(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://example.invalid")
    monkeypatch.setenv("ALL_PROXY", "http://example.invalid")
    http = client()
    assert not http.trust_env and not http.follow_redirects
    asyncio.run(http.aclose())


def test_multiple_calls_and_history_preserve_ids():
    body = dict(
        model=TAG,
        done=True,
        done_reason="stop",
        message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "get_order", "arguments": {"order_id": str(i)}}}
                for i in range(2)
            ],
        },
    )
    decision = parse_reply(body, "abc")
    assert [c.call_id for c in decision.calls] == ["abc_0", "abc_1"]
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "type": "function",
                    "id": c.call_id,
                    "function": {"name": c.name, "arguments": c.arguments_json},
                }
                for c in decision.calls
            ],
        },
        {"role": "tool", "tool_call_id": "abc_1", "content": "{}"},
    ]
    native = payload(profile(), messages, [])["messages"]
    assert native[0]["tool_calls"][1]["function"]["arguments"] == {"order_id": "1"}
    assert native[1]["tool_name"] == "get_order" and native[1]["tool_call_id"] == "abc_1"
    assert decision.usage.input_tokens is decision.usage.output_tokens is None


@pytest.mark.parametrize(
    "changes",
    [
        {"done_reason": "length"},
        {"model": "other"},
        {"eval_count": 257},
        {"prompt_eval_count": 4097},
        {"eval_count": True},
    ],
)
def test_incomplete_or_invalid_usage(changes):
    body = dict(
        model=TAG, done=True, done_reason="stop", message={"role": "assistant", "content": "ok"}
    )
    with pytest.raises(ModelFailure):
        parse_reply(body | changes, "abc")


def test_arbitrary_transport_rejected():
    with pytest.raises(ValueError):
        client(object())
