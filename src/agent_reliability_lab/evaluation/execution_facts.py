"""Defensive boundary classification for persisted evidence, not a substitute for seals."""

TERMINAL = {"completed", "failed", "tool_failed", "permission_denied", "budget_exhausted"}
STATUSES = TERMINAL | {"prepared", "running", "interrupted"}


def execution_facts(capture: object, *, evidence_hash=None, verify_hash=False) -> dict:
    facts = dict(
        classification="missing_execution",
        completed=False,
        status=None,
        resume_eligible=None,
        errors=[],
        malformed=False,
    )

    def invalid(code):
        return {
            **facts,
            "classification": "contradictory_evidence"
            if code.startswith("contradictory")
            else "malformed_execution",
            "malformed": True,
            "errors": [code],
        }

    if capture is None:
        return facts
    if not isinstance(capture, dict):
        return invalid("malformed_capture")
    if verify_hash:
        from agent_reliability_lab.opsdesk.fixtures import digest

        if not isinstance(evidence_hash, str):
            return invalid("missing_capture_hash")
        if digest(capture) != evidence_hash:
            return invalid("contradictory_capture_hash")
    execution = capture.get("execution")
    if execution is None:
        return facts
    if not isinstance(execution, dict):
        return invalid("malformed_execution")
    status = execution.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        return invalid("missing_or_malformed_execution_status")
    facts["status"] = status
    result = execution.get("result")
    if result is not None and not isinstance(result, dict):
        return invalid("malformed_execution_result")
    result = result or {}
    if "resume_eligible" in result and type(result["resume_eligible"]) is not bool:
        return invalid("malformed_resume_eligibility")
    stale_resume_result = (
        status == "running"
        and result.get("status") == "interrupted"
        and (result.get("resume_eligible") is True)
    )
    if "status" in result and result["status"] != status and not stale_resume_result:
        return invalid("contradictory_terminal_status")
    resumable = result.get("resume_eligible", status in {"prepared", "running", "interrupted"})
    facts["resume_eligible"] = resumable
    events = capture.get("events")
    if not isinstance(events, list):
        return invalid("missing_or_malformed_journal")
    for event in events:
        if (
            not isinstance(event, dict)
            or not isinstance(event.get("event_type"), str)
            or (
                type(event.get("sequence")) is not int or not isinstance(event.get("payload"), dict)
            )
        ):
            return invalid("malformed_journal_event")
    if status not in TERMINAL:
        facts["classification"] = (
            "incomplete_resumable" if resumable else "interrupted_nonresumable"
        )
        return facts
    if "resume_eligible" not in result or "status" not in result:
        return {
            **facts,
            "classification": "incomplete_execution",
            "errors": ["missing_terminal_result"],
        }
    if resumable:
        return invalid("contradictory_terminal_resume_eligibility")
    terminals = [
        e for e in events if e["event_type"] in {"run_completed", "run_failed", "run_interrupted"}
    ]
    if not terminals:
        return {
            **facts,
            "classification": "incomplete_execution",
            "errors": ["missing_terminal_event"],
        }
    terminal = max(terminals, key=lambda e: e["sequence"])
    if terminal["event_type"] != ("run_completed" if status == "completed" else "run_failed") or (
        terminal["payload"].get("status") != status
    ):
        return invalid("contradictory_terminal_event")
    return {**facts, "classification": "completed", "completed": True}
