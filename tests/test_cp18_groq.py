import pytest
from pydantic import ValidationError

from agent_reliability_lab.agent.errors import ModelFailure
from agent_reliability_lab.research.groq_model import groq_payload
from agent_reliability_lab.research.live_contracts import GroqProfile


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "openrouter"),
        ("eligibility", "developer_plan"),
        ("requested_model", "openai/gpt-oss-20b:free"),
        ("returned_model", "openai/gpt-oss-120b"),
        ("endpoint", "https://api.groq.com.invalid/openai/v1/chat/completions"),
        ("service_tier", "auto"),
        ("rolling_day_calls", 17),
        ("local_function_tools", False),
        ("input_ceiling", 131000),
    ],
)
def test_groq_profile_rejects_unapproved_routes_and_limits(field, value):
    settings = {"input_ceiling": 8000, "output_ceiling": 1024, field: value}
    with pytest.raises(ValidationError):
        GroqProfile.model_validate(settings)


def test_free_authorization_requires_free_organization_evidence_and_backend_pin():
    profile = GroqProfile(input_ceiling=8000, output_ceiling=1024)
    assert profile.incompatibilities("groq_free") == [
        "backend_fingerprint_not_pinned",
        "free_organization_unverified",
        "free_credential_not_pinned",
    ]
    assert profile.incompatibilities("paid_openai") == ["groq_paid_route_forbidden"]
    assert profile.incompatibilities("mock_http") == ["backend_fingerprint_not_pinned"]


def test_groq_request_rejects_provider_hosted_tools_and_unsupported_wire_fields():
    profile = GroqProfile(input_ceiling=8000, output_ceiling=1024)
    with pytest.raises(ModelFailure, match="groq_unsupported_message_name"):
        groq_payload(
            profile, [{"role": "user", "name": "unsupported", "content": "fixture"}], [], 100
        )
    with pytest.raises(ModelFailure, match="pilot_provider_hosted_tool_unsupported"):
        groq_payload(profile, [], [{"type": "browser_search"}], 100)
