"""CP15 contracts for a development-only provider pilot and budget ledger."""

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from agent_reliability_lab.benchmarks.scenario import Contract, Identifier
from agent_reliability_lab.evaluation.contracts import PriceBook
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.contracts import Artifact, Reference

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PhysicalID = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
ModelID = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")]
PilotModelID = ModelID | Literal["openai/gpt-oss-20b"]
ReportedModelID = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_./:-]{0,127}$")]
Money = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=12, allow_inf_nan=False)]
GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_PILOT_CALLS = 16
GROQ_CONTEXT = 131_072
GROQ_QUALIFICATION_INPUT = 256
GROQ_QUALIFICATION_OUTPUT = 256


class OllamaProfile(Contract):
    version: Literal["local-ollama-1"] = "local-ollama-1"
    tag: Literal["qwen3.5:4b"] = "qwen3.5:4b"
    endpoint: Literal["http://127.0.0.1:11434"] = "http://127.0.0.1:11434"
    model_digest: Hash
    runtime: Literal["0.40.16"] = "0.40.16"
    quantization: str = Field(min_length=1, max_length=64)
    template_hash: Hash
    hardware: dict[str, str | int | None]
    num_ctx: Literal[4096] = 4096
    num_predict: Literal[256] = 256
    temperature: Literal[0] = 0
    seed: Literal[42] = 42
    think: Literal[False] = False
    smoke: bool = False


class PilotModel(Contract):
    provider: Literal["openai", "groq", "ollama"] = "openai"
    model_id: PilotModelID
    allowed_models: tuple[PilotModelID, ...] = Field(min_length=1, max_length=16)
    local_profile: OllamaProfile | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    endpoint: Literal["chat_completions", "ollama_chat"] = "chat_completions"
    parallel_tool_calls: Literal[False] = False
    store: Literal[False] = False
    sdk_retries: Literal[0] = 0

    @model_validator(mode="after")
    def allowlist(self) -> Self:
        if (self.provider == "ollama") != (self.local_profile is not None) or (
            self.provider == "ollama"
        ) != (self.endpoint == "ollama_chat"):
            raise ValueError("native endpoint requires a local Ollama profile")
        if (
            self.model_id not in self.allowed_models
            or len(set(self.allowed_models)) != len(self.allowed_models)
            or self.provider == "openai"
            and GROQ_MODEL in self.allowed_models
        ):
            raise ValueError("invalid frozen model allowlist")
        return self


class PilotLimits(Contract):
    total_calls: int = Field(ge=1, le=10000)
    calls_per_scenario: int = Field(ge=1, le=10000)
    total_retries: int = Field(default=0, ge=0, le=10000)
    retries_per_turn: int = Field(ge=0, le=5)
    maximum_input_tokens: int = Field(ge=1, le=2000000)
    maximum_output_tokens: int = Field(ge=1, le=16384)
    total_tokens: int = Field(ge=1, le=20000000000)
    maximum_usd: Money
    duration_seconds: int = Field(ge=1, le=86400)


class PilotPlan(Artifact):
    kind: Literal["benchmark_pilot_plan"] = "benchmark_pilot_plan"
    authorization_version: Literal["development-pilot-1.0.0"] = "development-pilot-1.0.0"
    mode: Literal[
        "offline_fixture",
        "future_live_requested",
        "groq_qualification",
        "ollama_local",
        "ollama_mock",
    ]
    protocol: Reference
    supersedes: Reference | None = None
    schedule_hash: Hash
    ledger_id: PhysicalID
    model: PilotModel
    pricing: PriceBook
    pricing_hash: Hash
    limits: PilotLimits
    fixture_fault: Literal["none", "first_dispatch_timeout", "first_usage_missing"] = "none"

    @model_validator(mode="after")
    def bound_manifest(self) -> Self:
        if self.protocol.kind != "benchmark_protocol":
            raise ValueError("pilot requires a development benchmark protocol")
        if self.pricing_hash != digest(self.pricing.model_dump(mode="json")):
            raise ValueError("frozen pricing manifest fingerprint differs")
        if len(self.pricing.prices) != 1:
            raise ValueError("pilot requires one exact-model price")
        price = self.pricing.prices[0]
        if (price.provider, price.model_id) != (self.model.provider, self.model.model_id):
            raise ValueError("pricing and model configuration differ")
        rates = (price.input_rate, price.cached_input_rate or Decimal(0), price.output_rate)
        local = self.mode in {"ollama_local", "ollama_mock"}
        if local != (self.model.provider == "ollama"):
            raise ValueError("local plan and model must agree")
        if local:
            profile = self.model.local_profile
            if (
                self.model.allowed_models != (profile.tag,)
                or self.model.model_id != profile.tag
                or self.limits.total_calls != (4 if profile.smoke else 16)
                or self.limits.retries_per_turn
                or self.limits.total_retries
                or self.limits.maximum_output_tokens != profile.num_predict
                or self.limits.maximum_input_tokens != profile.num_ctx
                or self.limits.maximum_usd
                or any(rates)
                or price.fixed_request_fee
            ):
                raise ValueError("invalid local development budget")
        elif self.model.provider == "groq":
            if (
                self.mode not in {"future_live_requested", "groq_qualification"}
                or self.model.model_id != GROQ_MODEL
                or self.model.allowed_models != (GROQ_MODEL,)
                or self.limits.total_calls > GROQ_PILOT_CALLS
                or self.limits.retries_per_turn != 0
                or self.limits.total_retries != 0
                or self.limits.maximum_input_tokens + self.limits.maximum_output_tokens
                > GROQ_CONTEXT
                or self.limits.maximum_usd != 0
                or any(rates)
                or price.fixed_request_fee != 0
            ):
                raise ValueError("Groq requires the frozen Free-plan model and a zero-cost plan")
        elif self.limits.maximum_usd <= 0:
            raise ValueError("OpenAI pilot requires a positive USD ceiling")
        if self.mode == "groq_qualification" and (
            self.model.provider != "groq"
            or self.limits.total_calls != 1
            or self.limits.calls_per_scenario != 1
            or self.limits.maximum_input_tokens != GROQ_QUALIFICATION_INPUT
            or self.limits.maximum_output_tokens != GROQ_QUALIFICATION_OUTPUT
            or self.limits.total_tokens != GROQ_QUALIFICATION_INPUT + GROQ_QUALIFICATION_OUTPUT
        ):
            raise ValueError("qualification requires exactly one bounded Groq text request")
        if any(rate > 1000000 or rate.normalize().as_tuple().exponent < -6 for rate in rates):
            raise ValueError("pilot price exceeds supported precision or range")
        if (
            price.fixed_request_fee > 100
            or price.fixed_request_fee.normalize().as_tuple().exponent < -12
        ):
            raise ValueError("pilot request fee exceeds supported precision or range")
        if self.mode != "offline_fixture" and self.fixture_fault != "none":
            raise ValueError("fixture faults are available only offline")
        if (
            (self.version == 1) != (self.supersedes is None)
            or self.supersedes
            and (
                self.supersedes.kind,
                self.supersedes.identity,
                self.supersedes.version,
            )
            != (self.kind, self.identity, self.version - 1)
        ):
            raise ValueError("pilot amendments must pin the exact preceding plan version")
        return self

    def price_ceiling(self, inputs: int, outputs: int) -> Decimal:
        price = self.pricing.prices[0]
        return (
            inputs * max(price.input_rate, price.cached_input_rate or Decimal(0))
            + outputs * price.output_rate
        ) / Decimal(1000000) + price.fixed_request_fee


class PilotArm(Contract):
    slot: Identifier
    arm: Literal["baseline", "guarded"]
    scenario: Identifier
    tenant: Identifier
    actor: Identifier
    script_config_hash: Hash
    maximum_output_tokens: int = Field(ge=1, le=16384)


class CallRequest(Contract):
    attempt_id: PhysicalID
    execution_id: PhysicalID
    allocation: PilotArm
    turn: int = Field(ge=0)
    retry_of: PhysicalID | None = None
    model_config_hash: Hash
    pricing_hash: Hash
    input_hash: Hash
    estimated_input_tokens: int | None = Field(ge=0)
    maximum_output_tokens: int = Field(ge=1, le=16384)
    authorization_hash: Hash | None = Field(default=None, exclude_if=lambda value: value is None)
    wire_hash: Hash | None = Field(default=None, exclude_if=lambda value: value is None)


class ProviderObservation(Contract):
    outcome: Literal["completed", "failed"]
    reported_model: ReportedModelID | None = None
    provider_request_id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.:-]{1,128}$")] | None = None
    input_tokens: int | None = Field(default=None, ge=0, le=2000000000)
    output_tokens: int | None = Field(default=None, ge=0, le=2000000000)
    billed_usd: Money | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)
    response_hash: Hash | None = None
    http_status: int | None = Field(
        default=None, ge=100, le=599, exclude_if=lambda value: value is None
    )
    error_code: Identifier | None = Field(default=None, exclude_if=lambda value: value is None)
    cached_input_tokens: int | None = Field(
        default=None, ge=0, le=2000000000, exclude_if=lambda value: value is None
    )
    cache_write_tokens: int | None = Field(
        default=None, ge=0, le=2000000000, exclude_if=lambda value: value is None
    )
    reported_total_tokens: int | None = Field(
        default=None, ge=0, le=4000000000, exclude_if=lambda value: value is None
    )
    unpriced_usage: bool | None = Field(default=None, exclude_if=lambda value: value is None)
    invalid_metering: Literal[True] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    system_fingerprint: ModelID | None = Field(default=None, exclude_if=lambda value: value is None)
    route_mismatch: Literal[True] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    ollama_duration_ns: dict[str, Annotated[int, Field(ge=0)]] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    groq_rate_limits: dict[str, int | str] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class PilotReport(Artifact):
    kind: Literal["benchmark_pilot_report"] = "benchmark_pilot_report"
    version: Literal[1] = 1
    plan: Reference
    benchmark_result: Reference
    event_count: int = Field(ge=0)
    event_hash: Hash
    report_hash: Hash
