"""A vocabulary for observed evidence gaps, independent of scored failure labels."""

UNKNOWN = {
    "missing_model_observation": "No model observation is available at the required boundary.",
    "missing_tool_completion": "Dispatch has no verifiable terminal tool completion.",
    "missing_write_receipt": "No matched local write receipt establishes commitment.",
    "missing_provider_acknowledgment": "The dispatcher lacks a durable provider acknowledgment.",
    "missing_delivery_confirmation": "No authoritative terminal delivery event is available.",
    "contradictory_records": "Records disagree on a material identity or outcome.",
    "interrupted_execution": "Execution stopped at an interruption.",
    "incomplete_execution": "Execution has not reached a verified terminal outcome.",
    "insufficient_final_state_evidence": "The final state or its explanation is unavailable.",
    "infrastructure_failure": "An infrastructure failure prevents a complete observation.",
    "unverifiable_provenance": "Required provenance is missing or cannot be joined.",
}


def provider_gaps(evidence):
    result = []
    if evidence["provider_attempts"] and not evidence["acknowledged"]:
        result.append("missing_provider_acknowledgment")
    if evidence["delivery"] == "unknown":
        result.append("missing_delivery_confirmation")
    if evidence["delivery"] == "contradictory":
        result.append("contradictory_records")
    return result


def observed_trial_gaps(score):
    """Map only available, explicit diagnostics from a pinned score."""
    status = score.get("status")
    reasons = set()
    if status in {"incomplete_execution", "infrastructure_failure"}:
        reasons.add(status)
    if score.get("agent_status") == "interrupted":
        reasons.add("interrupted_execution")
    codes = {
        item.get("code")
        for item in (score.get("reconciliation") or {}).get("errors", [])
        if isinstance(item, dict)
    }
    translations = {
        "missing_attempt_completion": "missing_tool_completion",
        "successful_write_missing_receipt": "missing_write_receipt",
        "missing_model_response": "missing_model_observation",
        "unexplained_full_state_mutation": "insufficient_final_state_evidence",
        "journal_sequence_gap": "unverifiable_provenance",
    }
    reasons.update(translations[code] for code in codes if code in translations)
    if any(
        isinstance(code, str)
        and not code.startswith("missing_or_")
        and any(word in code for word in ("contradict", "conflict", "mismatch"))
        for code in codes
    ):
        reasons.add("contradictory_records")
    return sorted(reasons)
