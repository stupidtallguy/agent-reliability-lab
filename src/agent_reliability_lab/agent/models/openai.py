"""Official async Chat Completions SDK; state is local and hidden reasoning is not captured."""

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
)

from agent_reliability_lab.agent.errors import ModelFailure
from agent_reliability_lab.agent.state import Decision, ModelCall, Usage


def parse_completion(response) -> Decision:
    if not response.choices:
        raise ModelFailure("invalid_model_response")
    choice = response.choices[0]
    if choice.finish_reason in {"length", "content_filter"}:
        raise ModelFailure("model_output_incomplete")
    message = choice.message
    calls = []
    for item in message.tool_calls or []:
        if item.type != "function":
            raise ModelFailure("unsupported_model_tool")
        calls.append(
            ModelCall(
                call_id=item.id, name=item.function.name, arguments_json=item.function.arguments
            )
        )
    usage = response.usage
    counts = Usage()
    if usage is not None:
        counts = Usage(
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cached_input_tokens=getattr(usage.prompt_tokens_details, "cached_tokens", None),
            reasoning_tokens=getattr(usage.completion_tokens_details, "reasoning_tokens", None),
            source="provider",
        )
    return Decision(
        answer=message.content,
        calls=calls,
        usage=counts,
        reported_model=response.model,
        provider_request_id=getattr(response, "_request_id", None),
    )


async def request_completion(client, model_id, messages, tools, max_output_tokens):
    tool_options = {"tools": tools, "parallel_tool_calls": False} if tools else {}
    return await client.chat.completions.create(
        model=model_id,
        messages=messages,
        max_completion_tokens=max_output_tokens,
        store=False,
        **tool_options,
    )


class OpenAIModel:
    def __init__(self, model_id: str, *, live_opt_in: bool = False, client=None):
        if not live_opt_in:
            raise ValueError("real model requests require explicit --live opt-in")
        self.model_id = model_id
        self.client = client or AsyncOpenAI(max_retries=0, base_url="https://api.openai.com/v1")

    async def decide(
        self, messages: list[dict], tools: list[dict], turn: int, max_output_tokens: int
    ) -> Decision:
        try:
            response = await request_completion(
                self.client, self.model_id, messages, tools, max_output_tokens
            )
            return parse_completion(response)
        except ModelFailure:
            raise
        except APITimeoutError:
            raise ModelFailure("model_timeout", True) from None
        except RateLimitError:
            raise ModelFailure("rate_limited", True) from None
        except (AuthenticationError, NotFoundError):
            raise ModelFailure("model_unavailable") from None
        except APIConnectionError:
            raise ModelFailure("provider_unavailable", True) from None
        except APIStatusError:
            raise ModelFailure("provider_error") from None

    async def close(self):
        await self.client.close()
