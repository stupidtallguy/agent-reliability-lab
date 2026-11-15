"""Verify the notification publication evidence independently of report fields."""

import sqlalchemy as sa

from agent_reliability_lab.opsdesk import tables as business
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.reliability import notifications as n
from agent_reliability_lab.reliability.inspection import retry_chain
from agent_reliability_lab.reliability.metrics import Observation, notification_metrics
from agent_reliability_lab.reliability.verification import logical_commitment, operation_attempts


def select_chain(connection, execution, operation, identifier, key):
    """Caller holds the notification lock and conflicting table writes are blocked."""
    config = execution["config"]
    identity = {
        "actor_id": config["actor_id"],
        "tenant_id": config["tenant_id"],
        "marker": execution["context"]["marker"],
    }
    run = config["sandbox_run_id"]
    # The demo's run schema may be reclaimed after the evidence is frozen.
    active = connection.scalar(sa.select(business.registry.c.marker).filter_by(run_id=run))
    rows = list(
        connection.execute(
            sa.select(n.intents).filter_by(
                **identity,
                run_id=run,
                operation_key=key,
            )
        ).mappings()
    )
    admission = connection.scalar(sa.select(n.admissions.c.run_id).filter_by(**identity))
    if (active is not None and active != identity["marker"]) or admission != run:
        raise ValueError("contradictory live sandbox ownership")
    message = n.lookup(connection, n.outbox, identifier)
    intent = rows[0] if len(rows) == 1 else None
    response = operation["response"]["data"]
    payload = {field: response[field] for field in ("customer_id", "template")}
    if (
        not intent
        or not message
        or intent["notification_id"] != identifier
        or digest([identity, key]) != identifier
        or response["notification_id"] != identifier
        or intent["receipt"] != response
        or digest(payload) != operation["arguments_hash"]
        or intent["payload_hash"] != operation["arguments_hash"]
        or message["payload_hash"] != intent["payload_hash"]
    ):
        raise ValueError("contradictory committed intent or outbox")
    return {"intent": dict(intent), "outbox": dict(message), "mutation_count": len(rows)}


def canonical_metrics(document, snapshot, operation, records):
    provider = document["provider"]
    local = snapshot["local"]
    proofs = operation_attempts(operation, snapshot["attempts"], records)
    lifecycle = logical_commitment(operation, proofs)
    if lifecycle != "verified":
        raise ValueError(f"{lifecycle} logical operation lifecycle")
    exported = document["retry"]
    observed = [
        {k: row[k] for k in ("ordinal", "attempt_id", "status", "effect")}
        | {"error": row.get("error_code")}
        for row in snapshot["attempts"]
    ]
    intent = local["intent"]
    binding = document["execution_evidence"]
    receipt = exported.get("receipt") or {}
    execution = snapshot["execution"]
    config = execution["config"]
    if (
        observed != exported.get("attempts")
        or len(observed) != document.get("physical_tool_attempts")
        or document.get("logical_operation_count") != 1
        or document.get("local_mutations") != local["mutation_count"]
        or document.get("receipt_count") != 1
        or type(local["mutation_count"]) is not int
        or local["mutation_count"] != 1
        or exported.get("outcome") != "committed"
        or exported.get("arguments_hash") != operation["arguments_hash"]
        or intent["receipt"] != operation["response"]["data"]
        or intent["marker"] != execution["context"]["marker"]
        or intent["run_id"] != config["sandbox_run_id"]
        or intent["actor_id"] != config["actor_id"]
        or intent["tenant_id"] != config["tenant_id"]
        or intent["operation_key"] != binding["operation_key"]
        or intent["payload_hash"] != operation["arguments_hash"]
        or intent["notification_id"] != provider["notification_id"]
        or local["outbox"]["notification_id"] != provider["notification_id"]
        or local["outbox"]["payload_hash"] != operation["arguments_hash"]
        or receipt.get("outbox_payload_hash") != operation["arguments_hash"]
        or provider.get("local_intent") != "recorded"
        or provider.get("integrity_issue") is not None
        or provider.get("provider_operation_id")
        != digest(
            [
                "synthetic-provider",
                provider["notification_id"],
                local["intent"]["operation_key"],
                operation["arguments_hash"],
            ]
        )
    ):
        raise ValueError("contradictory publication counters or identity")
    successes = [
        p
        for p in proofs
        if p.attempt["status"] == "succeeded"
        and p.response.get("data") == local["intent"]["receipt"]
    ]
    if not successes:
        raise ValueError("missing verified receipt attempt")
    projected = retry_chain(
        {
            "operations": [operation],
            "attempts": snapshot["attempts"],
            "provenance": records,
            "notification_intent": intent,
        },
        operation["proposal_id"],
        {
            "committed": {
                operation["operation_id"]: {
                    "notification_id": provider["notification_id"],
                    "receipt_hash": digest(intent["receipt"]),
                    "outbox_payload_hash": operation["arguments_hash"],
                }
            }
        },
    )
    if any(
        value != exported.get(key)
        for key, value in projected.items()
        if key not in {"outcome", "receipt_reuse", "logical_reconciliation"}
    ):
        raise ValueError("contradictory frozen retry evidence")
    if exported.get("logical_reconciliation") != lifecycle:
        raise ValueError("contradictory publication lifecycle claim")
    faults = []
    retries = {}
    markers = [
        r
        for r in records
        if r["kind"] == "reliability_receipt_observed"
        and r["reference"] == operation["operation_id"]
    ]
    for proof in proofs:
        if proof.attempt["error_code"] != "transport_unavailable":
            continue
        recovery = next((p for p in successes if p.start_sequence > proof.response_sequence), None)
        verified_reuse = recovery is not None and any(
            proof.start_sequence < marker["sequence"] < proof.response_sequence
            and marker["body"]
            == {
                "proposal_id": operation["proposal_id"],
                "receipt_hash": digest(local["intent"]["receipt"]),
            }
            for marker in markers
        )
        outcome = True if verified_reuse else None
        faults.append(Observation(proof.attempt["attempt_id"], outcome))
        if recovery:
            identity = recovery.attempt["attempt_id"]
            retries[identity] = Observation(identity, outcome)
    if exported.get("receipt_reuse") != (
        "verified for attempt 2"
        if any(row.outcome is True for row in retries.values())
        else "unresolved"
    ):
        raise ValueError("contradictory receipt-reuse claim")
    conflicts = []
    for row in provider["rejected_conflicting_intents"]:
        if (
            row["notification_id"] != provider["notification_id"]
            or row["payload_hash"] == operation["arguments_hash"]
            or row["conflict_id"] != digest([row["notification_id"], row["payload_hash"]])
        ):
            raise ValueError("contradictory intent rejection evidence")
        conflicts.append(Observation(row["conflict_id"], True))
    return notification_metrics(
        provider,
        operation_id=operation["operation_id"],
        mutation_count=local["mutation_count"],
        receipt_reconciled=True,
        attempt_observations=list(retries.values()),
        faults=faults,
        conflicts=conflicts,
        dispatched=bool(observed),
    )


def require_metrics(submitted, expected):
    """Canonical JSON equality rejects extra fields and type aliases as well as false counts."""
    if not isinstance(submitted, list) or digest(submitted) != digest(expected):
        raise ValueError("invalid or unsupported reliability metrics")
