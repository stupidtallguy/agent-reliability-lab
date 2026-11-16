"""Frozen authorization and provider compatibility for development HTTP pilots."""

import re
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from agent_reliability_lab.benchmarks.scenario import Contract, Identifier
from agent_reliability_lab.research.contracts import Artifact, Reference
from agent_reliability_lab.research.pilot_contracts import Hash, ModelID, PhysicalID, PilotLimits


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


class LiveAuthorization(Artifact):
    kind: Literal["benchmark_live_authorization"] = "benchmark_live_authorization"
    authorization_version: Literal["development-http-1.0.0"] = "development-http-1.0.0"
    decision: Literal["authorized", "revoked"]
    mode: Literal["mock_http", "paid_openai"]
    scope: Identifier
    protocol: Reference
    pilot: Reference
    experiment: Identifier
    schedule_hash: Hash
    configuration_hash: Hash
    pricing_hash: Hash
    ledger_id: PhysicalID
    profile: ProviderProfile
    limits: PilotLimits
    starts_at: AwareDatetime
    deadline: AwareDatetime
    supersedes: Reference | None = None

    @model_validator(mode="after")
    def validity(self) -> Self:
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
