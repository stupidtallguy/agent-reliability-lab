"""Compare sealed input fingerprints without retaining model messages."""

import json
import re

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
        for identity in (previous, current):
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
            fingerprint = body.get("input_hash")
            if not isinstance(fingerprint, str) or not HASH.fullmatch(fingerprint):
                raise ValueError("missing_or_invalid_input_hash")
            if (
                body.get("execution_id") != execution_id
                or event.get("execution_id") != execution_id
                or body.get("request_id") != identity
                or not isinstance(event.get("sequence"), int)
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
        (left, first), (right, second) = boundaries
        if previous != current and (
            first["sequence"] >= right["sequence"]
            or first["body"]["sequence"] >= second["body"]["sequence"]
        ):
            raise ValueError("contradictory_request_order")
        a, b = left["body"], right["body"]
        result["relation"] = "identical" if a["input_hash"] == b["input_hash"] else "changed"
        result["boundary"] = (
            "same_request"
            if previous == current
            else ("same_turn_model_retry" if a["turn"] == b["turn"] else "new_decision")
        )
        x, y = a.get("context", {}), b.get("context", {})
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
