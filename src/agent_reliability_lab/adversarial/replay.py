"""Canonical scripted replay checks; never deterministic hosted-model replay."""

from agent_reliability_lab.evaluation.contracts import Evidence
from agent_reliability_lab.evaluation.oracles import changes
from agent_reliability_lab.opsdesk.fixtures import digest


def canonical(evidence: Evidence) -> dict:
    if evidence.execution["config"]["model"]["provider"] != "fake":
        raise ValueError("canonical replay comparison is limited to scripted executions")
    operations = {op["proposal_id"]: op for op in evidence.operations}
    attempts = {a["attempt_id"]: a for a in evidence.attempts}
    names = {}
    for audit in evidence.audits:
        if audit["operation"] == "create_task":
            # Logical mutation order is reproducible; task IDs derive from run-scoped
            # receipt keys and intentionally vary between physical sandboxes.
            names[audit["task_id"]] = f"created_task_{audit['sequence']}"

    def normalize(value):
        if isinstance(value, dict):
            return {names.get(k, k): normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [normalize(v) for v in value]
        return names.get(value, value) if isinstance(value, str) else value

    boundaries = []
    for event in evidence.events:
        if event["event_type"] not in {
            "injection_trigger",
            "injection_activated",
            "injection_observed",
        }:
            continue
        p = event["payload"]
        op = operations[p["tool_call_id"]]
        boundaries.append(
            {
                "kind": event["event_type"],
                "injection_id": p["injection_id"],
                "configuration_hash": p["configuration_hash"],
                "logical_proposal": [op["turn"], op["position"]],
                "attempt_ordinal": attempts[p["attempt_id"]]["ordinal"],
                "boundary": p.get("boundary"),
                "matched": p.get("matched"),
                "payload_delivered": p.get("payload_delivered"),
                "error_code": p.get("error_code"),
            }
        )
    return {
        "version": "1.0",
        "initial_hash": evidence.initial_hash,
        "boundaries": boundaries,
        "operations": [
            {"tool": op["tool"], "arguments": normalize(op["arguments"]), "status": op["status"]}
            for op in evidence.operations
        ],
        "changes": normalize(changes(evidence.initial, evidence.final)),
        "agent_result": {
            key: (evidence.execution.get("result") or {}).get(key)
            for key in ("status", "answer", "response_completed")
        },
    }


def fingerprint(evidence: Evidence) -> str:
    return digest(canonical(evidence))


def verify_replay(original: Evidence, repeated: Evidence) -> str:
    if fingerprint(original) != fingerprint(repeated):
        raise ValueError("scripted logical replay diverged")
    return fingerprint(original)
