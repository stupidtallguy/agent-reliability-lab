from typing import Protocol, runtime_checkable

from agent_reliability_lab.agent.state import Decision


class ModelAdapter(Protocol):
    async def decide(
        self, messages: list[dict], tools: list[dict], turn: int, max_output_tokens: int
    ) -> Decision: ...


@runtime_checkable
class EvidenceBoundModel(Protocol):
    async def decide_for_request(
        self,
        execution_id: str,
        request_id: str,
        messages: list[dict],
        tools: list[dict],
        turn: int,
        max_output_tokens: int,
    ) -> Decision: ...
