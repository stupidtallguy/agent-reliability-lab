"""Frozen authorization and provider compatibility for development HTTP pilots."""

import re
from hashlib import sha256
from secrets import compare_digest
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from agent_reliability_lab.benchmarks.scenario import Contract, Identifier
from agent_reliability_lab.research.contracts import Artifact, Reference
from agent_reliability_lab.research.pilot_contracts import (
    GROQ_CONTEXT,
    GROQ_PILOT_CALLS,
    Hash,
    ModelID,
    PhysicalID,
    PilotLimits,
)


class ProviderProfile(Contract):
    schema_version: Literal["openai-chat-text-1.0"] = "openai-chat-text-1.0"
    endpoint: Literal["https://api.openai.com/v1/chat/completions"] = (
        "https://api.openai.com/v1/chat/completions"
    )
    provider: Literal["openai"] = "openai"
    requested_model: ModelID
    returned_model: ModelID
    textual_function_tools: bool
    output_limit_supported: bool
    input_ceiling: int = Field(ge=1, le=2000000)
    output_ceiling: int = Field(ge=1, le=16384)
    billing: Literal["standard_text_rates_and_fixed_fee", "unbounded"]
    price_review: Literal["synthetic", "unverified", "externally_reviewed"]
    spend_control: Literal["simulation", "unverified", "externally_enforced"]
    evidence_reference: Identifier
    provider_project: ModelID | None = None

    def incompatibilities(self, mode):
        issues = []
        if self.requested_model != self.returned_model or not re.search(
            r"-20\d{2}-\d{2}-\d{2}$", self.requested_model
        ):
            issues.append("model_alias_or_identity_incompatible")
        if not self.textual_function_tools or not self.output_limit_supported:
            issues.append("tool_or_output_limit_incompatible")
        if self.billing != "standard_text_rates_and_fixed_fee":
            issues.append("unbounded_billing_categories")
        if mode == "paid_openai":
            if self.price_review != "externally_reviewed":
                issues.append("pricing_review_unavailable")
            if self.spend_control != "externally_enforced":
                issues.append("external_spend_safeguard_unverified")
            if self.provider_project is None:
                issues.append("provider_project_not_pinned")
        elif (self.price_review, self.spend_control) != ("synthetic", "simulation"):
            issues.append("mock_requires_synthetic_pricing_and_safeguard")
        return issues


class GroqPacing(Contract):
    """Operator-observed ceilings, conservatively capped at public Free-plan limits."""

    requests_per_minute: int = Field(ge=1, le=30)
    requests_per_day: int = Field(ge=1, le=1000)
    tokens_per_minute: int = Field(ge=1, le=8000)
    tokens_per_day: int = Field(ge=1, le=200000)
    input_tokens_per_minute: int | None = Field(default=None, ge=1, le=8000)
    output_tokens_per_minute: int | None = Field(default=None, ge=1, le=8000)

    @model_validator(mode="after")
    def split_limits(self) -> Self:
        if (self.input_tokens_per_minute is None) != (self.output_tokens_per_minute is None):
            raise ValueError("record both split token ceilings when configured")
        return self


class GroqProfile(Contract):
    schema_version: Literal["groq-free-chat-1.0"] = "groq-free-chat-1.0"
    endpoint: Literal["https://api.groq.com/openai/v1/chat/completions"] = (
        "https://api.groq.com/openai/v1/chat/completions"
    )
    provider: Literal["groq"] = "groq"
    requested_model: Literal["openai/gpt-oss-20b"] = "openai/gpt-oss-20b"
    returned_model: Literal["openai/gpt-oss-20b"] = "openai/gpt-oss-20b"
    service_tier: Literal["on_demand"] = "on_demand"
    reasoning_effort: Literal["medium"] = "medium"
    include_reasoning: Literal[False] = False
    eligibility: Literal["groq_public_free_plan_2026_11_16"] = "groq_public_free_plan_2026_11_16"
    local_function_tools: Literal[True] = True
    input_ceiling: int = Field(ge=1, lt=GROQ_CONTEXT)
    output_ceiling: int = Field(ge=1, le=16384)
    rolling_day_calls: Literal[16] = GROQ_PILOT_CALLS
    expected_system_fingerprint: ModelID | None = None
    free_organization_evidence: Hash | None = None
    free_key_commitment: Hash | None = None
    pacing: GroqPacing | None = Field(default=None, exclude_if=lambda value: value is None)
    fingerprint_qualification: Reference | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    qualification_event_hash: Hash | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def window(self) -> Self:
        if (self.fingerprint_qualification is None) != (self.qualification_event_hash is None):
            raise ValueError("a fingerprint pin requires the qualification and its event hash")
        if self.input_ceiling + self.output_ceiling > GROQ_CONTEXT:
            raise ValueError("Groq input and output limits exceed the published context window")
        pacing = self.pacing
        if pacing and (
            self.input_ceiling + self.output_ceiling
            > min(pacing.tokens_per_minute, pacing.tokens_per_day)
            or pacing.input_tokens_per_minute is not None
            and self.input_ceiling > pacing.input_tokens_per_minute
            or pacing.output_tokens_per_minute is not None
            and self.output_ceiling > pacing.output_tokens_per_minute
        ):
            raise ValueError("one reserved request must fit the frozen Groq token ceilings")
        return self

    def incompatibilities(self, mode, *, qualification=False):
        if mode == "paid_openai":
            return ["groq_paid_route_forbidden"]
        issues = []
        if qualification and (
            self.expected_system_fingerprint is not None or self.fingerprint_qualification
        ):
            issues.append("qualification_requires_unpinned_backend")
        if not qualification and self.expected_system_fingerprint is None:
            issues.append("backend_fingerprint_not_pinned")
        if mode == "groq_free" or qualification:
            if self.free_organization_evidence is None:
                issues.append("free_organization_unverified")
            if self.free_key_commitment is None:
                issues.append("free_credential_not_pinned")
        return issues

    def matches_credential(self, credential):
        return bool(
            credential
            and self.free_key_commitment
            and compare_digest(self.free_key_commitment, groq_key_commitment(credential))
        )


def groq_key_commitment(credential):
    return sha256(
        b"agent-reliability-lab/groq-free-key/v1\0" + credential.encode("utf-8")
    ).hexdigest()


class LiveAuthorization(Artifact):
    kind: Literal["benchmark_live_authorization"] = "benchmark_live_authorization"
    authorization_version: Literal["development-http-1.0.0", "development-groq-free-1.0.0"] = (
        "development-http-1.0.0"
    )
    decision: Literal["authorized", "revoked"]
    mode: Literal["mock_http", "paid_openai", "groq_free"]
    scope: Identifier
    protocol: Reference
    pilot: Reference
    experiment: Identifier
    schedule_hash: Hash
    configuration_hash: Hash
    pricing_hash: Hash
    ledger_id: PhysicalID
    profile: ProviderProfile | GroqProfile
    limits: PilotLimits
    starts_at: AwareDatetime
    deadline: AwareDatetime
    supersedes: Reference | None = None
    purpose: Literal["groq_fingerprint"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validity(self) -> Self:
        groq = isinstance(self.profile, GroqProfile)
        if self.purpose and not groq:
            raise ValueError("fingerprint qualification is available only for Groq")
        if groq != (self.authorization_version == "development-groq-free-1.0.0") or (
            self.mode != "mock_http" and groq != (self.mode == "groq_free")
        ):
            raise ValueError("provider mode and authorization version disagree")
        if self.deadline <= self.starts_at or self.created_at >= self.deadline:
            raise ValueError("authorization window must have a valid finite deadline")
        if (
            (self.version == 1) != (self.supersedes is None)
            or self.supersedes
            and (self.supersedes.kind, self.supersedes.identity, self.supersedes.version)
            != (self.kind, self.identity, self.version - 1)
        ):
            raise ValueError("authorization requires exact previous version")
        if self.decision == "revoked" and self.supersedes is None:
            raise ValueError("revocation requires a prior authorization")
        return self
