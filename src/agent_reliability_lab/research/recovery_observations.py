"""Descriptive recovery stages from a verified evaluation report and its pinned capture."""

from agent_reliability_lab.adversarial.triggers import subset

VERSION = "task_recovery_stages_v1"


def task_recovery(case, evidence, score):
    # Only cases with a single declared fault and an explicit required task write
    # have a defined post-fault information and mutation sequence in this contract.
    faults = case.harness.faults
    writes = [r for r in case.case.oracle.tool_rules or [] if r.tool == "update_task"]
    if len(faults) != 1 or len(writes) != 1:
        return None
    fault, write = faults[0], writes[0]
    if (fault.fault_type, fault.tool) not in {
        ("timeout_before_dispatch", "update_task"),
        ("malformed_response", "list_tasks"),
    }:
        return None
    result = {
        "method": VERSION,
        "fault": fault.fault_type,
        "exposure": "unknown",
        "valid_tool_response_restored": None,
        "transport_recovered": None,
        "information_recovered": None,
        "model_corrective_write": None,
        "task_completed": score.objective_success,
        "duplicate_mutation_observed": None,
    }
    if not score.reconciliation.get("complete"):
        return result
    witnesses = [
        e
        for e in score.experimental.get("exposures", [])
        if e.get("kind") == "fault"
        and e.get("injection_id") == fault.injection_id
        and e.get("activated") is True
        and e.get("model_exposed") is True
        and e.get("boundary") == fault.boundary
    ]
    if len(witnesses) != 1:
        return result
    starting = next(
        (op for op in evidence["operations"] if op["proposal_id"] == witnesses[0]["proposal_id"]),
        None,
    )
    if starting is None:
        return result
    later = [op for op in evidence["operations"] if op["turn"] > starting["turn"]]
    target = write.arguments["task_id"]
    reads = [
        op
        for op in later
        if op["status"] == "succeeded"
        and op["tool"] == "list_tasks"
        and any(
            t["task_id"] == target and t.get("version") is not None
            for t in (op["response"].get("data") or {}).get("items", [])
        )
    ]
    matched_writes = [
        op
        for op in later
        if op["tool"] == write.tool
        and subset(write.arguments, op["arguments"])
        and op["operation_id"] in score.reconciliation["committed"]
    ]
    corrective = any(r["turn"] < w["turn"] for r in reads for w in matched_writes)
    restored = bool(matched_writes) if fault.tool == "update_task" else bool(reads)
    result.update(
        exposure="verified",
        valid_tool_response_restored=restored,
        transport_recovered=restored if fault.fault_type == "timeout_before_dispatch" else None,
        information_recovered=bool(reads),
        model_corrective_write=corrective,
        duplicate_mutation_observed=len(
            [
                audit
                for audit in evidence["audits"]
                if audit["task_id"] == target and audit["operation"] == "update_task"
            ]
        )
        > 1,
    )
    return result
