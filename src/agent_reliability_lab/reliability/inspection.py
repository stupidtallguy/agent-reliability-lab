"""Read-only retry inspection over persisted operations and sealed model requests."""

from agent_reliability_lab.agent.provenance import verify
from agent_reliability_lab.evaluation.evidence import normalized_task
from agent_reliability_lab.mcp.context import receipt_key
from agent_reliability_lab.mcp.contracts import CreateTaskInput, UpdateTaskInput
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.reliability.context import compare_requests
from agent_reliability_lab.reliability.diagnostics import observed_trial_gaps
from agent_reliability_lab.reliability.verification import operation_attempts


def task_commitment(evidence, operation, attempts, committed):
    if not committed or operation.get("tool") not in {"create_task", "update_task"}:
        return False
    config = (evidence.get("execution") or {}).get("config") or {}
    try:
        tool = operation["tool"]
        key = receipt_key(
            dict(
                run=config["sandbox_run_id"],
                actor=config["actor_id"],
                tenant=config["tenant_id"],
                tool=tool,
                operation=operation["operation_id"],
            )
        )
        model = CreateTaskInput if tool == "create_task" else UpdateTaskInput
        fingerprint = digest(model.model_validate(operation["arguments"]).model_dump(mode="json"))
        receipts = [
            r
            for r in evidence.get("receipts", [])
            if (
                r["idempotency_key"],
                r["actor_id"],
                r["tenant_id"],
                r["operation"],
                r["request_hash"],
            )
            == (key, config["actor_id"], config["tenant_id"], tool, fingerprint)
        ]
        if len(receipts) != 1 or (committed.get("receipt_key"), committed.get("proposal_id")) != (
            key,
            operation["proposal_id"],
        ):
            return False
        payload = normalized_task(receipts[0]["response"])
        audits = [
            r
            for r in evidence.get("audits", [])
            if (r["actor_id"], r["tenant_id"], r["operation"], r["sequence"])
            == (config["actor_id"], config["tenant_id"], tool, committed.get("audit_sequence"))
            and normalized_task(r["after"]) == payload
        ]
        proofs = operation_attempts(operation, attempts, evidence.get("provenance") or [])
        return len(audits) == 1 and any(
            proof.attempt["status"] == "succeeded"
            and isinstance(proof.response.get("data"), dict)
            and normalized_task(proof.response["data"]) == payload
            for proof in proofs
        )
    except (KeyError, TypeError, ValueError):
        return False


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
    target = (operation.get("arguments") or {}).get("task_id")
    audit_observed = bool(target) and any(
        audit.get("task_id") == target and audit.get("operation") == operation["tool"]
        for audit in evidence.get("audits", [])
    )
    denied = bool(attempts) and all(row.get("effect") == "denied" for row in attempts)
    contradiction = "contradictory_records" in observed_trial_gaps(
        {"reconciliation": reconciliation or {}}
    ) or bool(committed and denied)
    verified = (reconciliation or {}).get("complete") is True and task_commitment(
        evidence, operation, attempts, committed
    )
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
        "mutation_evidence": "observed"
        if committed
        else ("observed_on_target" if audit_observed else "unresolved"),
        "outcome": "contradictory"
        if contradiction
        else ("committed" if verified else "denied" if denied else "unknown"),
        # Returned task receipts do not tell the host which physical attempt originally committed.
        "receipt_reuse": "not independently observable" if len(attempts) > 1 else "not applicable",
    }
