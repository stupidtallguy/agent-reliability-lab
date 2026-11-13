"""Candidate 1.7 joins of sealed ledger facts and their journal projections."""

import re

from agent_reliability_lab.agent.provenance_v2 import identity, verify_projection_v2


def verify_projection_v3(evidence):
    verify_projection_v2(evidence)
    records = evidence.provenance

    def unique(kind):
        selected = [r for r in records if r["kind"] == kind]
        if len({r["reference"] for r in selected}) != len(selected):
            raise ValueError(f"contradictory_duplicate_{kind}")
        return {r["reference"]: r for r in selected}

    starts, ends = unique("model_started"), unique("model_completed")
    proposals, responses = unique("original_proposal"), unique("tool_response")
    journals = unique("journal_event")
    by_sequence = {r["body"]["sequence"]: r for r in journals.values()}
    if len({r["request_id"] for r in evidence.requests}) != len(evidence.requests):
        raise ValueError("contradictory_duplicate_request_projection")

    def event(kind, key, value):
        matching = [
            e for e in evidence.events if e["event_type"] == kind and e["payload"].get(key) == value
        ]
        if len(matching) != 1:
            raise ValueError(f"{'missing' if not matching else 'contradictory'}_{kind}_boundary")
        return matching[0], by_sequence[matching[0]["sequence"]]

    for request in evidence.requests:
        rid = request["request_id"]
        sealed = starts[rid]
        begin, boundary = event("model_request", "request_id", rid)
        value = sealed["body"].get("input_hash")
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("missing_or_malformed_sealed_input_hash")
        if begin["payload"].get("input_hash") != value:
            raise ValueError("contradictory_sealed_request_input_hash")
        if boundary["body"]["payload"].get("turn") != request["turn"]:
            raise ValueError("missing_or_contradictory_request_journal_turn")
        for field in ("provider", "model"):
            if identity(begin["payload"].get(field), field) != identity(
                sealed["body"].get(field), field
            ):
                raise ValueError("contradictory_request_journal_model_identity")
        if sealed["sequence"] >= boundary["sequence"]:
            raise ValueError("contradictory_sealed_request_start_order")
        if request["status"] != "completed":
            continue
        completed = ends[rid]
        _, finish = event("model_response", "request_id", rid)
        if (
            not sealed["sequence"]
            < boundary["sequence"]
            < completed["sequence"]
            < finish["sequence"]
        ):
            raise ValueError("contradictory_sealed_decision_order")
        for marker in evidence.events:
            if (
                marker["event_type"] != "injection_model_exposure"
                or marker["payload"].get("request_id") != rid
            ):
                continue
            observation = by_sequence[marker["sequence"]]
            response = responses.get(marker["payload"].get("attempt_id"))
            if response is None:
                raise ValueError("missing_sealed_observation_response")
            if marker["payload"].get("input_hash") != value:
                raise ValueError("contradictory_sealed_exposure_input_hash")
            if (
                not response["sequence"]
                < sealed["sequence"]
                < boundary["sequence"]
                < observation["sequence"]
                < completed["sequence"]
            ):
                raise ValueError("contradictory_sealed_observation_order")

    proposal_boundaries = {}
    for op in evidence.operations:
        request = next(
            r for r in evidence.requests if r["turn"] == op["turn"] and r["status"] == "completed"
        )
        projected, proposed = event("tool_call_proposed", "tool_call_id", op["proposal_id"])
        for key, expected in dict(
            tool=op["tool"],
            logical_operation_id=op["operation_id"],
            arguments_hash=op["arguments_hash"],
        ).items():
            if key not in projected["payload"] or projected["payload"][key] != expected:
                raise ValueError(f"missing_or_contradictory_proposal_journal_{key}")
        if (
            not ends[request["request_id"]]["sequence"]
            < proposals[op["proposal_id"]]["sequence"]
            < proposed["sequence"]
        ):
            raise ValueError("contradictory_sealed_proposal_order")
        proposal_boundaries[op["proposal_id"]] = proposed["sequence"]
    for attempt in evidence.attempts:
        _, dispatch = event("tool_call_started", "attempt_id", attempt["attempt_id"])
        proposed = proposal_boundaries.get(attempt["proposal_id"])
        if proposed is None or proposed >= dispatch["sequence"]:
            raise ValueError("missing_or_contradictory_sealed_dispatch_order")
        if attempt["status"] == "started":
            continue
        kind = "tool_call_succeeded" if attempt["status"] == "succeeded" else "tool_call_failed"
        _, completion = event(kind, "attempt_id", attempt["attempt_id"])
        if (
            not dispatch["sequence"]
            < completion["sequence"]
            < responses[attempt["attempt_id"]]["sequence"]
        ):
            raise ValueError("contradictory_sealed_response_order")
