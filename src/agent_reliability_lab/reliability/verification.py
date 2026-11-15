"""Evidence joins shared by reliability publication and operation inspection."""

from dataclasses import dataclass

from agent_reliability_lab.agent.provenance import verify
from agent_reliability_lab.evaluation.evidence import response_projection
from agent_reliability_lab.opsdesk.fixtures import digest


@dataclass(frozen=True)
class AttemptProof:
    attempt: dict
    response: dict
    start_sequence: int
    response_sequence: int


def operation_attempts(operation, attempts, records):
    """Require sealed intent, dispatch and completion for each reported success."""
    verify(records, operation["execution_id"])
    proposal = operation["proposal_id"]
    originals = [
        r for r in records if r["kind"] == "original_proposal" and r["reference"] == proposal
    ]
    keys = ("proposal_id", "execution_id", "operation_id", "tool", "arguments_hash")
    if (
        len(originals) != 1
        or any(originals[0]["body"].get(k) != operation.get(k) for k in keys)
        or not operation.get("operation_id")
        or digest(operation["arguments"]) != operation["arguments_hash"]
    ):
        raise ValueError("missing or contradictory original operation")
    proofs = []
    seen = set()
    dispatched = {
        row["body"]["payload"]["attempt_id"]
        for row in records
        if row["kind"] == "journal_event"
        and row["body"].get("event_type") == "tool_call_started"
        and row["body"].get("payload", {}).get("tool_call_id") == proposal
    }
    if dispatched != {attempt["attempt_id"] for attempt in attempts}:
        raise ValueError("contradictory attempt inventory")
    for ordinal, attempt in enumerate(attempts, 1):
        identifier = attempt["attempt_id"]
        if (
            identifier in seen
            or attempt["proposal_id"] != proposal
            or attempt["ordinal"] != ordinal
        ):
            raise ValueError("contradictory attempt identity")
        seen.add(identifier)
        journal = [
            r
            for r in records
            if r["kind"] == "journal_event"
            and r["body"].get("payload", {}).get("attempt_id") == identifier
            and r["body"]["event_type"]
            in ("tool_call_started", "tool_call_succeeded", "tool_call_failed")
        ]
        sealed = [
            r for r in records if r["kind"] == "tool_response" and r["reference"] == identifier
        ]
        identity = {
            "tool_call_id": proposal,
            "logical_operation_id": operation["operation_id"],
            "tool": operation["tool"],
        }
        if (
            not journal
            or journal[0]["body"]["event_type"] != "tool_call_started"
            or journal[0]["sequence"] <= originals[0]["sequence"]
            or journal[0]["body"]["payload"].get("ordinal") != attempt["ordinal"]
            or any(
                record["body"].get("execution_id") != operation["execution_id"]
                or any(record["body"]["payload"].get(key) != val for key, val in identity.items())
                for record in journal
            )
        ):
            raise ValueError("contradictory attempt dispatch identity")
        if attempt["status"] == "started":
            if len(journal) != 1 or sealed:
                raise ValueError("contradictory unfinished attempt lifecycle")
            continue
        if len(journal) != 2 or len(sealed) != 1:
            raise ValueError("missing or contradictory attempt records")
        start, done = journal
        raw = sealed[0]["body"]
        response = raw["response"]
        error = (response.get("error") or {}).get("code")
        expected = "succeeded" if error is None else "failed"
        effect = (
            "receipt_confirmed"
            if error is None
            else ("denied" if error in {"permission_denied", "approval_required"} else "unknown")
        )
        if (
            done["body"]["event_type"] != "tool_call_" + expected
            or not start["sequence"] < done["sequence"] < sealed[0]["sequence"]
            or raw.get("proposal_id") != proposal
            or raw.get("attempt_id") != identifier
            or raw.get("operation_id") != operation["operation_id"]
            or done["body"]["payload"].get("response_hash") != digest(response)
            or done["body"]["payload"].get("error_code") != error
            or done["body"]["payload"].get("effect") != effect
            or (attempt["status"], attempt.get("error_code"), attempt["effect"])
            != (expected, error, effect)
        ):
            raise ValueError("contradictory attempt lifecycle")
        proofs.append(AttemptProof(attempt, response, start["sequence"], sealed[0]["sequence"]))
    return proofs


def matches_response(operation, proof):
    captured = operation.get("response")
    return captured == proof.response or captured == response_projection(proof.response)


def logical_commitment(operation, proofs):
    """Separate a sealed business effect from reconciliation of the logical lifecycle."""
    status = operation.get("status")
    successes = [proof for proof in proofs if proof.attempt["status"] == "succeeded"]
    if len({digest(proof.response.get("data")) for proof in successes}) > 1:
        return "contradictory"
    if status == "succeeded":
        if not proofs:
            return "unresolved"
        return (
            "verified"
            if any(matches_response(operation, proof) for proof in successes)
            else "contradictory"
        )
    if successes and (
        status in {"prepared", "rejected"}
        or proofs[-1].attempt["status"] == "succeeded"
        or any(matches_response(operation, proof) for proof in successes)
    ):
        return "contradictory"
    # A committed effect can precede an acknowledgment failure.
    return "unresolved"
