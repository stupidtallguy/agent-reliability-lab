"""Trusted host settings; credentials never belong in this model or checkpoints."""

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from agent_reliability_lab.adversarial.contracts import Defense, RuntimePlan
from agent_reliability_lab.benchmarks.scenario import Contract, Identifier
from agent_reliability_lab.mcp.contracts import Domain
from agent_reliability_lab.opsdesk.database import schema_for


class Budgets(Contract):
    max_known_tokens: int | None = Field(default=None, ge=1, exclude_if=lambda value: value is None)
    max_estimated_cost: Decimal | None = Field(
        default=None, gt=0, allow_inf_nan=False, exclude_if=lambda value: value is None
    )
    price_schedule: dict | None = Field(default=None, exclude_if=lambda value: value is None)
    max_llm_calls: Annotated[int, Field(ge=1, le=100)] = 8
    max_tool_calls: Annotated[int, Field(ge=1, le=100)] = 16
    max_graph_steps: Annotated[int, Field(ge=1, le=1000)] = 64
    max_retries: Annotated[int, Field(ge=0, le=5)] = 1
    max_wall_seconds: Annotated[float, Field(gt=0, le=3600)] = 120.0
    model_timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 30.0
    tool_timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 20.0
    max_output_tokens: Annotated[int, Field(ge=1, le=16384)] = 1024
    max_context_bytes: Annotated[int, Field(ge=256, le=1000000)] = 65536
    max_result_bytes: Annotated[int, Field(ge=256, le=65536)] = 16384
    max_answer_chars: Annotated[int, Field(ge=1, le=32768)] = 8000


class ModelConfig(Contract):
    provider: Literal["fake", "openai"] = "fake"
    model_id: str = Field(default="scripted-v1", min_length=1, max_length=256)
    script: list[dict] = Field(default_factory=list, max_length=100)
    repeat_last: bool = False


class AgentConfig(Contract):
    source_commit: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{40}$", exclude_if=lambda value: value is None
    )
    sandbox_run_id: str
    actor_id: Identifier
    tenant_id: Identifier
    model: ModelConfig = Field(default_factory=ModelConfig)
    budgets: Budgets = Field(default_factory=Budgets)
    domains: list[Domain] = Field(default_factory=lambda: ["documents", "business", "tasks"])
    allowed_tools: list[str] | None = None
    transport: Literal["stdio", "memory"] = "stdio"
    runtime_plan: RuntimePlan | None = Field(default=None, exclude_if=lambda value: value is None)
    defense: Defense | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def valid_host(self) -> Self:
        schema_for(self.sandbox_run_id)
        if not self.domains or len(self.domains) != len(set(self.domains)):
            raise ValueError("domains must be nonempty and unique")
        if "notifications" in self.domains and (
            self.model.provider != "fake"
            or self.defense is not None
            or self.runtime_plan is not None
            or not self.sandbox_run_id.startswith("rel_")
        ):
            raise ValueError("notifications are available only in the scripted reliability lab")
        if not self.model.model_id.strip():
            raise ValueError("an explicit model ID is required")
        if self.model.provider == "openai" and self.model.model_id == "scripted-v1":
            raise ValueError("OpenAI requires an explicit provider model ID")
        return self
