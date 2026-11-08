from typing import Protocol

from agent_reliability_lab.agent.state import Decision


class ModelAdapter(Protocol):
    async def decide(
        self, messages: list[dict], tools: list[dict], turn: int, max_output_tokens: int
    ) -> Decision: ...
