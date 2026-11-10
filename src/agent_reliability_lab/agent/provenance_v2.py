"""Candidate 1.6 projection checks; historical projection semantics stay frozen."""

from pydantic import ValidationError

from agent_reliability_lab.agent.provenance import verify, verify_projection
from agent_reliability_lab.agent.state import Decision


def identity(value: object, field: str) -> str:
    """Providers are case-insensitive; exact model IDs are case-sensitive, untrimmed."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"missing_or_malformed_model_identity_{field}")
    if value.casefold() in {"[redacted]", "<redacted>"}:
        raise ValueError(f"unsupported_redacted_model_identity_{field}")
    return value.casefold() if field == "provider" else value


def verify_model_identity(evidence) -> None:
    verify(evidence.provenance, evidence.execution_id)
    config = evidence.execution.get("config")
    model = config.get("model") if isinstance(config, dict) else None
    if not isinstance(model, dict):
        raise ValueError("missing_captured_model_identity")
    expected = {
        "provider": identity(model.get("provider"), "provider"),
        "model": identity(model.get("model_id"), "model"),
    }
    starts = [r for r in evidence.provenance if r["kind"] == "model_started"]
    if len({r["reference"] for r in starts}) != len(starts):
        raise ValueError("contradictory_sealed_request_identity")
    if {r["reference"] for r in starts} != {r["request_id"] for r in evidence.requests}:
        raise ValueError("missing_or_contradictory_sealed_requests")
    for record in starts:
        body = record["body"]
        if not isinstance(body, dict):
            raise ValueError("unsupported_malformed_sealed_request_identity")
        if body.get("execution_id") != evidence.execution_id:
            raise ValueError("contradictory_sealed_request_execution")
        if body.get("request_id") != record["reference"]:
            raise ValueError("contradictory_sealed_request_reference")
        for field, value in expected.items():
            if identity(body.get(field), field) != value:
                raise ValueError(f"contradictory_model_identity_{field}")


def verify_decision_sources(evidence) -> None:
    """Completed raw decisions are authoritative even before operations materialize."""
    completions = [r for r in evidence.provenance if r["kind"] == "model_completed"]
    if len({r["reference"] for r in completions}) != len(completions):
        raise ValueError("contradictory_sealed_decision_identity")
    by_id = {r["reference"]: r["body"] for r in completions}
    for request in evidence.requests:
        completed = by_id.get(request["request_id"])
        if request["status"] == "completed":
            if request["request_id"] not in by_id:
                raise ValueError("missing_sealed_decision")
            if not isinstance(completed, dict) or not isinstance(completed.get("reply"), dict):
                raise ValueError("unsupported_malformed_sealed_decision")
            if "calls" not in completed["reply"]:
                raise ValueError("missing_sealed_original_proposals")
            try:
                Decision.model_validate(completed["reply"])
            except ValidationError:
                raise ValueError("unsupported_malformed_original_decision") from None
            if (
                completed.get("execution_id") != evidence.execution_id
                or completed.get("request_id") != request["request_id"]
                or completed.get("turn") != request["turn"]
                or completed.get("reply", {}).get("calls") != request["calls"]
            ):
                raise ValueError("contradictory_sealed_original_decision")
        elif completed is not None or request.get("calls"):
            raise ValueError("contradictory_request_completion_state")
    if set(by_id) - {r["request_id"] for r in evidence.requests}:
        raise ValueError("contradictory_orphan_sealed_decision")


def verify_projection_v2(evidence) -> None:
    verify_model_identity(evidence)
    verify_decision_sources(evidence)
    verify_projection(evidence)
