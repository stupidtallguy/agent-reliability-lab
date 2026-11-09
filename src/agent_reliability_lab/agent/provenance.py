"""Versioned append-only seals. Integrity, not authentication against a DB owner."""

from datetime import datetime

from agent_reliability_lab.opsdesk.fixtures import digest


def portable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: portable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [portable(item) for item in value]
    return value


def seal(execution_id, sequence, kind, reference, body, previous_hash):
    record = dict(
        schema_version="1.0",
        execution_id=execution_id,
        sequence=sequence,
        kind=kind,
        reference=reference,
        body=portable(body),
        previous_hash=previous_hash,
    )
    record["body_hash"] = digest(record["body"])
    record["record_hash"] = digest(record)
    return record


def verify(records, execution_id):
    if not records:
        raise ValueError("missing_immutable_provenance")
    previous = None
    for sequence, record in enumerate(records, 1):
        expected = seal(
            execution_id, sequence, record["kind"], record["reference"], record["body"], previous
        )
        if record != expected:
            raise ValueError("contradictory_provenance_chain")
        previous = record["record_hash"]
    if records[0]["kind"] != "execution_created":
        raise ValueError("unsupported_unsealed_execution_prefix")
    return previous


def verify_projection(evidence):
    """Compare the frozen collector projection with the original sealed records."""
    from agent_reliability_lab.evaluation.evidence import EVENT_KEYS, response_projection

    records = evidence.provenance
    verify(records, evidence.execution_id)
    events = [r["body"] for r in records if r["kind"] == "journal_event"]
    projected = [
        {**event, "payload": {k: v for k, v in event["payload"].items() if k in EVENT_KEYS}}
        for event in events
    ]
    if projected != evidence.events:
        raise ValueError("contradictory_sealed_journal")
    completions = {r["reference"]: r["body"] for r in records if r["kind"] == "model_completed"}
    starts = {r["reference"]: r["body"] for r in records if r["kind"] == "model_started"}
    if set(starts) != {r["request_id"] for r in evidence.requests}:
        raise ValueError("missing_or_contradictory_sealed_requests")
    for request in evidence.requests:
        start = starts.get(request["request_id"])
        if start is None:
            raise ValueError("missing_sealed_request")
        if any(start[k] != request[k] for k in ("execution_id", "turn", "request_id")):
            raise ValueError("contradictory_sealed_request_identity")
        if request["status"] == "completed":
            original = completions.get(request["request_id"])
            if original is None:
                raise ValueError("missing_sealed_decision")
            reply = original["reply"]
            if reply["calls"] != request["calls"] or digest(reply.get("answer")) != request.get(
                "answer_hash"
            ):
                raise ValueError("contradictory_sealed_decision")
            if (
                reply["usage"] != request["usage"]
                or reply.get("reported_model") != request["model"]
                or original["duration_ms"] != request["duration_ms"]
            ):
                raise ValueError("contradictory_sealed_decision_metadata")
    proposals = {r["reference"]: r["body"] for r in records if r["kind"] == "original_proposal"}
    if set(proposals) != {op["proposal_id"] for op in evidence.operations}:
        raise ValueError("missing_or_contradictory_sealed_proposals")
    for op in evidence.operations:
        original = proposals.get(op["proposal_id"])
        if original is None:
            raise ValueError("missing_sealed_proposal")
        for key in (
            "execution_id",
            "turn",
            "position",
            "tool",
            "model_call_id",
            "operation_id",
            "arguments",
            "arguments_hash",
        ):
            if original[key] != op[key]:
                raise ValueError("contradictory_sealed_proposal")

        origins = [
            r for r in evidence.requests if r["turn"] == op["turn"] and r["status"] == "completed"
        ]
        if len(origins) != 1 or original["original"] != origins[0]["calls"][op["position"]]:
            raise ValueError("contradictory_sealed_original_call")
        responses = [
            r["body"]
            for r in records
            if r["kind"] == "tool_response" and r["body"]["proposal_id"] == op["proposal_id"]
        ]
        attempts = [
            a
            for a in evidence.attempts
            if a["proposal_id"] == op["proposal_id"] and a["status"] != "started"
        ]
        if {r["attempt_id"] for r in responses} != {a["attempt_id"] for a in attempts}:
            raise ValueError("missing_or_contradictory_sealed_responses")
        for response in responses:
            if response["operation_id"] != op["operation_id"]:
                raise ValueError("contradictory_sealed_response_operation")
        if attempts:
            last = max(attempts, key=lambda a: a["ordinal"])
            response = next(r for r in responses if r["attempt_id"] == last["attempt_id"])
            if response_projection(response["response"]) != op["response"]:
                raise ValueError("contradictory_sealed_response_projection")
