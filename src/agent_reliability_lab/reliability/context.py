"""Compare sealed input fingerprints without retaining model messages."""

import json
import re
from itertools import pairwise

from agent_reliability_lab.agent.provenance import verify
from agent_reliability_lab.opsdesk.fixtures import digest

VERSION = "1.0"
HASH = re.compile(r"[0-9a-f]{64}")


def fingerprints(messages, model, *, max_output_tokens):
    observations = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        payload = json.loads(message["content"])
        response = payload.get("observation", payload)
        data = response.get("data") or {}
        items = data.get("items") if isinstance(data, dict) else None
        documents = (
            [
                {"document_id": item["document_id"], "version": item.get("version")}
                for item in [data, *(items if isinstance(items, list) else [])]
                if isinstance(item, dict) and "document_id" in item
            ]
            if isinstance(data, dict)
            else []
        )
        observations.append(
            {
                "position": len(observations),
                "hash": digest(payload),
                "documents": documents,
            }
        )
    return {
        "fingerprint_version": VERSION,
        "instructions_hash": digest(
            [m for m in messages if m.get("role") in {"system", "developer"}]
        ),
        "model_config_hash": digest([model.model_dump(mode="json"), max_output_tokens]),
        "observations": observations,
    }


def _check_components(context):
    if not isinstance(context, dict):
        raise ValueError("malformed_input_components")
    for key in ("instructions_hash", "tool_schema_hash"):
        value = context.get(key)
        if value is None:
            raise ValueError("missing_input_components")
        if not isinstance(value, str) or not HASH.fullmatch(value):
            raise ValueError("malformed_input_components")
    observations = context.get("observations")
    if observations is None:
        raise ValueError("missing_input_components")
    if not isinstance(observations, list) or any(
        not isinstance(row, dict)
        or row.get("position") != position
        or not isinstance(row.get("hash"), str)
        or not HASH.fullmatch(row["hash"])
        or not isinstance(row.get("documents"), list)
        or any(
            not isinstance(doc, dict)
            or not isinstance(doc.get("document_id"), str)
            or type(doc.get("version")) not in (str, int, type(None))
            for doc in row["documents"]
        )
        for position, row in enumerate(observations)
    ):
        raise ValueError("malformed_input_components")


def compare_requests(records, execution_id, previous, current):
    """Join the original ledger boundaries before interpreting hash equality."""
    result = {
        "version": VERSION,
        "previous": previous,
        "current": current,
        "relation": "unverifiable",
        "changes": [],
        "references": [],
    }
    try:
        verify(records, execution_id)
        boundaries = []
        between = [row["reference"] for row in records if row["kind"] == "model_started"]
        if previous in between and current in between and previous != current:
            start_index, end_index = between.index(previous), between.index(current)
            identities = (
                between[start_index : end_index + 1]
                if start_index < end_index
                else (previous, current)
            )
        else:
            identities = [previous] if previous == current else [previous, current]
        for identity in identities:
            starts = [
                r for r in records if r["kind"] == "model_started" and r["reference"] == identity
            ]
            journal = [
                r
                for r in records
                if r["kind"] == "journal_event"
                and r["body"].get("event_type") == "model_request"
                and r["body"].get("payload", {}).get("request_id") == identity
            ]
            if len(starts) > 1 or len(journal) > 1:
                raise ValueError("contradictory_request_identity")
            if not starts or not journal:
                raise ValueError("missing_request_boundary")
            start, entry = starts[0], journal[0]
            body, event = start["body"], entry["body"]
            boundary = event["payload"]
            turn = body.get("turn")
            if turn is None:
                raise ValueError("missing_model_turn")
            if type(turn) is not int or turn < 0:
                raise ValueError("contradictory_model_turn")
            fingerprint = body.get("input_hash")
            if not isinstance(fingerprint, str) or not HASH.fullmatch(fingerprint):
                raise ValueError("missing_or_invalid_input_hash")
            if (
                body.get("execution_id") != execution_id
                or event.get("execution_id") != execution_id
                or body.get("request_id") != identity
                or type(event.get("sequence")) is not int
                or event["sequence"] < 1
                or start["sequence"] >= entry["sequence"]
                or any(
                    body.get(k) != boundary.get(k)
                    for k in ("turn", "provider", "model", "input_hash")
                )
            ):
                raise ValueError("contradictory_input_boundary")
            completions = [
                r for r in records if r["kind"] == "model_completed" and r["reference"] == identity
            ]
            if len(completions) > 1 or any(
                r["sequence"] <= entry["sequence"]
                or r["body"].get("execution_id") != execution_id
                or r["body"].get("request_id") != identity
                or r["body"].get("turn") != body["turn"]
                for r in completions
            ):
                raise ValueError("contradictory_decision_boundary")
            exposures = [
                r
                for r in records
                if r["kind"] == "journal_event"
                and r["body"].get("event_type") == "injection_model_exposure"
                and r["body"].get("payload", {}).get("request_id") == identity
            ]
            if any(
                r["body"].get("execution_id") != execution_id
                or r["body"]["payload"].get("input_hash") != fingerprint
                or r["sequence"] <= entry["sequence"]
                or r["body"]["sequence"] <= event["sequence"]
                or (completions and r["sequence"] >= completions[0]["sequence"])
                for r in exposures
            ):
                raise ValueError("contradictory_exposure_boundary")
            result["references"].append(
                {
                    "request": identity,
                    "ledger": start["sequence"],
                    "journal": event["sequence"],
                    "decision_ledger": completions[0]["sequence"] if completions else None,
                    "exposure_markers": [
                        {"journal": r["body"]["sequence"], "decision_recorded": bool(completions)}
                        for r in exposures
                    ],
                }
            )
            boundaries.append((start, entry))
        (left, first), (right, second) = boundaries[0], boundaries[-1]
        if previous != current and (
            first["sequence"] >= right["sequence"]
            or first["body"]["sequence"] >= second["body"]["sequence"]
        ):
            raise ValueError("contradictory_request_order")
        a, b = left["body"], right["body"]
        for index, ((older, earlier), (newer, later)) in enumerate(pairwise(boundaries)):
            before, after = older["body"]["turn"], newer["body"]["turn"]
            decision = result["references"][index]["decision_ledger"]
            if earlier["sequence"] >= newer["sequence"] or (
                earlier["body"]["sequence"] >= later["body"]["sequence"]
            ):
                raise ValueError("contradictory_request_order")
            if after < before:
                raise ValueError("contradictory_model_turn")
            if after > before + 1 or (after > before and decision is None):
                raise ValueError("missing_intervening_decision")
            if after == before and decision is not None:
                raise ValueError("contradictory_completed_model_retry")
            if decision is not None and decision >= newer["sequence"]:
                raise ValueError("contradictory_decision_order")
        x, y = a.get("context", {}), b.get("context", {})
        input_components = ("instructions_hash", "tool_schema_hash", "observations")
        if a["input_hash"] == b["input_hash"]:
            if any(key in x and key in y and x[key] != y[key] for key in input_components):
                raise ValueError("contradictory_input_components")
        for boundary, _ in boundaries:
            _check_components(boundary["body"].get("context", {}))
        result["relation"] = "identical" if a["input_hash"] == b["input_hash"] else "changed"
        result["boundary"] = (
            "same_request"
            if previous == current
            else ("same_turn_model_retry" if a["turn"] == b["turn"] else "new_decision")
        )
        for key in (
            "system_template_hash",
            "instructions_hash",
            "tool_schema_hash",
            "model_config_hash",
            "max_output_tokens",
            "observations",
        ):
            if key in x and key in y and x[key] != y[key]:
                result["changes"].append(key)
        if (a["provider"], a["model"]) != (b["provider"], b["model"]):
            result["changes"].append("model_identity")
        if "observations" in result["changes"]:
            result["observations"] = {"previous": x["observations"], "current": y["observations"]}
        if any(
            first["sequence"] < r["sequence"] < right["sequence"]
            and r["kind"] == "journal_event"
            and r["body"].get("event_type") == "run_resumed"
            for r in records
        ):
            result["resumed_between"] = True
    except (KeyError, TypeError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "malformed_provenance"
        result.update(
            relation="contradictory" if reason.startswith("contradictory") else "unverifiable",
            reason=reason,
        )
    return result
