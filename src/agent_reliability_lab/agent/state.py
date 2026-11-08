"""JSON-only graph state and a result that is not a ground-truth score."""

from typing import Literal, TypedDict

from pydantic import Field

from agent_reliability_lab.benchmarks.scenario import Contract

Status = Literal[
    "prepared",
    "running",
    "interrupted",
    "completed",
    "permission_denied",
    "tool_failed",
    "budget_exhausted",
    "failed",
]
TERMINAL = {"completed", "permission_denied", "tool_failed", "budget_exhausted", "failed"}


class Usage(Contract):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    source: Literal["provider", "scripted", "unavailable"] = "unavailable"


class ModelCall(Contract):
    call_id: str = Field(max_length=128)
    name: str = Field(max_length=128)
    arguments_json: str = Field(max_length=16384)
    blocked_sensitive: bool = False


class Decision(Contract):
    answer: str | None = Field(default=None, max_length=32768)
    calls: list[ModelCall] = Field(default_factory=list, max_length=100)
    declared_complete: bool | None = None
    usage: Usage = Field(default_factory=Usage)
    reported_model: str | None = Field(default=None, max_length=256)
    provider_request_id: str | None = Field(default=None, max_length=256)


class AgentState(TypedDict):
    execution_id: str
    messages: list[dict]
    turn: int
    decision: dict
    pending: list[str]
    cursor: int
    status: str
    reason: str | None
    answer: str
    declared_complete: bool | None
    response_completed: bool
    tool_errors: bool
    denied: bool
    retry: bool


class AgentResult(Contract):
    execution_id: str
    thread_id: str
    status: Status
    answer: str
    response_completed: bool
    agent_declared_completion: bool | None
    objectively_verified: Literal[False] = False
    tool_call_count: int
    llm_call_count: int
    graph_step_count: int
    duration_seconds: float
    timing_complete: bool
    usage: dict
    reason: str | None
    resume_eligible: bool
    checkpoint_id: str | None
    trace_reference: str
