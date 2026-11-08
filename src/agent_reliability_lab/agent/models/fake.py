"""Script position comes from durable graph state, not an in-process iterator."""

import copy
import json

from agent_reliability_lab.agent.config import ModelConfig
from agent_reliability_lab.agent.state import Decision


class ScriptedModel:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.observed_messages: list[list[dict]] = []

    async def decide(
        self, messages: list[dict], tools: list[dict], turn: int, max_output_tokens: int
    ) -> Decision:
        self.observed_messages.append(copy.deepcopy(messages))
        if not self.config.script:
            return Decision(
                answer="No scripted action was configured.",
                declared_complete=False,
                reported_model=self.config.model_id,
            )
        index = min(turn, len(self.config.script) - 1) if self.config.repeat_last else turn
        if index >= len(self.config.script):
            return Decision(
                answer="Scripted conversation ended.",
                declared_complete=False,
                reported_model=self.config.model_id,
            )
        payload = copy.deepcopy(self.config.script[index])
        # A bounded infrastructure control can branch on actual lower-trust
        # observations. It has no evaluator/oracle access and is not an LLM.
        if "if_observation" in payload:
            condition = payload["if_observation"]
            if (
                set(payload) != {"if_observation", "then", "else"}
                or not isinstance(condition, str)
                or not 1 <= len(condition) <= 200
            ):
                raise ValueError("invalid scripted observation condition")
            observation = json.dumps(
                [m for m in messages if m.get("role") == "tool"], ensure_ascii=False
            )
            payload = payload["then"] if condition in observation else payload["else"]
        for position, call in enumerate(payload.get("calls", [])):
            call.setdefault("call_id", f"script_{turn}_{position}")
        payload.setdefault("reported_model", self.config.model_id)
        return Decision.model_validate(payload)
