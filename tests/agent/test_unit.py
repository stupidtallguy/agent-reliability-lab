import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import RateLimitError
from pydantic import ValidationError

from agent_reliability_lab.agent.config import Budgets, ModelConfig
from agent_reliability_lab.agent.errors import ModelFailure
from agent_reliability_lab.agent.journal import Redactor
from agent_reliability_lab.agent.models.fake import ScriptedModel
from agent_reliability_lab.agent.models.openai import OpenAIModel, parse_completion
from agent_reliability_lab.agent.persistence import JSONSerializer
from agent_reliability_lab.agent.state import Decision
from agent_reliability_lab.agent.tool_adapter import provider_tools


def completion(*, reason="stop", usage=None, calls=None):
    return NS(
        choices=[NS(finish_reason=reason, message=NS(content="Answer", tool_calls=calls))],
        usage=usage,
        model="requested-model-snapshot",
        _request_id="req_example",
    )


def test_schema_conversion_preserves_optional_fields_and_is_independent():
    catalog = [
        {
            "name": "list_tasks",
            "description": "List tasks.",
            "input_schema": {
                "type": "object",
                "properties": {"limit": {"default": 20}},
                "additionalProperties": False,
            },
        }
    ]
    result = provider_tools(catalog)[0]["function"]
    assert result["description"] == "List tasks."
    assert result["strict"] is False
    assert result["parameters"] == catalog[0]["input_schema"]
    result["parameters"]["properties"].clear()
    assert catalog[0]["input_schema"]["properties"]


@pytest.mark.anyio
async def test_fake_turn_index_survives_new_instance():
    config = ModelConfig(script=[{"answer": "first"}, {"answer": "second"}])
    assert (await ScriptedModel(config).decide([], [], 1, 100)).answer == "second"
    assert (await ScriptedModel(config).decide([], [], 2, 100)).declared_complete is False


@pytest.mark.parametrize("reason", ["length", "content_filter"])
def test_incomplete_completion(reason):
    with pytest.raises(ModelFailure, match="model_output_incomplete"):
        parse_completion(completion(reason=reason))


def test_parse_function_calls_and_nullable_usage():
    calls = [
        NS(
            id="model_call",
            type="function",
            function=NS(name="get_order", arguments='{"order_id":"order_001"}'),
        )
    ]
    decision = parse_completion(completion(calls=calls))
    assert decision.calls[0].name == "get_order"
    assert decision.usage.input_tokens is None
    assert decision.declared_complete is None
    usage = NS(
        prompt_tokens=12,
        completion_tokens=8,
        prompt_tokens_details=None,
        completion_tokens_details=NS(reasoning_tokens=3),
    )
    parsed = parse_completion(completion(usage=usage)).usage
    assert (parsed.input_tokens, parsed.output_tokens, parsed.reasoning_tokens) == (12, 8, 3)
    assert parsed.cached_input_tokens is None


@pytest.mark.anyio
async def test_real_adapter_offline_sdk_request_no_fallback():
    create = AsyncMock(return_value=completion())
    client = NS(chat=NS(completions=NS(create=create)))
    adapter = OpenAIModel("explicit-model", live_opt_in=True, client=client)
    decision = await adapter.decide([{"role": "user", "content": "hello"}], [], 0, 47)
    assert decision.reported_model == "requested-model-snapshot"
    assert create.call_args.kwargs["model"] == "explicit-model"
    assert create.call_args.kwargs["max_completion_tokens"] == 47
    assert create.call_args.kwargs["store"] is False
    assert create.await_count == 1


@pytest.mark.anyio
async def test_rate_limit_safe_and_not_retried():
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1"))
    create = AsyncMock(
        side_effect=RateLimitError("private diagnostic", response=response, body=None)
    )
    adapter = OpenAIModel(
        "model", live_opt_in=True, client=NS(chat=NS(completions=NS(create=create)))
    )
    with pytest.raises(ModelFailure, match="rate_limited") as caught:
        await adapter.decide([], [], 0, 100)
    assert "private" not in str(caught.value)
    assert caught.value.retryable
    assert create.await_count == 1


def test_real_adapter_requires_opt_in():
    with pytest.raises(ValueError, match="opt-in"):
        OpenAIModel("model")


@pytest.mark.parametrize(
    "field,value",
    [("max_llm_calls", 0), ("max_retries", -1), ("max_tool_calls", 101), ("max_wall_seconds", 0)],
)
def test_invalid_budgets(field, value):
    with pytest.raises(ValidationError):
        Budgets(**{field: value})


def test_redaction_bounds_and_json_only_serializer(monkeypatch):
    monkeypatch.setenv("EXAMPLE_API_KEY", "synthetic-sensitive-credential")
    redactor = Redactor()
    cleaned = redactor.clean({"value": "synthetic-sensitive-credential", "password": "short"})
    assert cleaned == {"value": "[REDACTED]", "password": "[REDACTED]"}
    assert redactor.capture("x" * 5000)["truncated"]
    serde = JSONSerializer()
    assert serde.loads_typed(serde.dumps_typed({"messages": []})) == {"messages": []}
    assert "secret" not in json.dumps(serde.loads_typed(serde.dumps_typed(ValueError("secret"))))
    with pytest.raises(ValueError):
        serde.loads_typed(("pickle", b"anything"))


def test_bounded_model_payload():
    with pytest.raises(ValidationError):
        Decision(calls=[{"call_id": "x", "name": "get_order", "arguments_json": "x" * 16385}])
