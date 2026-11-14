"""Read-only retry inspection over persisted operations and sealed model requests."""

from agent_reliability_lab.agent.provenance import verify
from agent_reliability_lab.reliability.context import compare_requests


def retry_chain(evidence, proposal_id, reconciliation=None):
    operation = next(
        (row for row in evidence.get("operations", []) if row.get("proposal_id") == proposal_id),
        None,
    )
    if operation is None or not operation.get("operation_id"):
        return None
    operation_id = operation["operation_id"]
    attempts = sorted(
        (row for row in evidence.get("attempts", []) if row.get("proposal_id") == proposal_id),
        key=lambda row: row["ordinal"],
    )
    provenance = evidence.get("provenance") or []
    execution_id = operation["execution_id"]
    try:
        verify(provenance, execution_id)
    except (KeyError, TypeError, ValueError):
        provenance = []
    requests = [row for row in provenance if row.get("kind") == "model_started"]
    completions = [
        row
        for row in provenance
        if row.get("kind") == "model_completed" and row["body"].get("turn") == operation["turn"]
    ]
    origins = [
        row for row in requests if any(c["reference"] == row["reference"] for c in completions)
    ]
    original = origins[0]["reference"] if len(origins) == len(completions) == 1 else None
    adjacent = []
    if original:
        index = [row["reference"] for row in requests].index(original)
        if index:
            adjacent.append(
                compare_requests(
                    provenance,
                    execution_id,
                    requests[index - 1]["reference"],
                    original,
                )
            )
        if index + 1 < len(requests):
            adjacent.append(
                compare_requests(
                    provenance,
                    execution_id,
                    original,
                    requests[index + 1]["reference"],
                )
            )
    committed = (reconciliation or {}).get("committed", {}).get(operation_id)
    return {
        "proposal_id": proposal_id,
        "logical_operation_id": operation_id,
        "arguments_hash": operation.get("arguments_hash"),
        "tool": operation.get("tool"),
        "model_requests": [original] if original else [],
        "context_comparisons": adjacent,
        "attempts": [
            {
                "ordinal": row["ordinal"],
                "attempt_id": row["attempt_id"],
                "status": row["status"],
                "error": row.get("error_code"),
                "effect": row.get("effect"),
            }
            for row in attempts
        ],
        "receipt": committed,
        "outcome": "committed"
        if committed
        else (
            "denied"
            if attempts and all(row.get("effect") == "denied" for row in attempts)
            else "unknown"
        ),
        # Returned task receipts do not tell the host which physical attempt originally committed.
        "receipt_reuse": "not independently observable" if len(attempts) > 1 else "not applicable",
    }
