"""Join host intents, physical attempts, MCP receipts and independent mutation audits."""

import copy
import json

from pydantic import ValidationError

from agent_reliability_lab.evaluation.contracts import Evidence
from agent_reliability_lab.evaluation.evidence import normalized_task
from agent_reliability_lab.evaluation.oracles import changes, same
from agent_reliability_lab.mcp.context import receipt_key
from agent_reliability_lab.mcp.contracts import CreateTaskInput, UpdateTaskInput
from agent_reliability_lab.opsdesk.fixtures import digest, from_scenario


def reconcile(scenario, evidence: Evidence) -> dict:
    errors = []

    def error(code, reference):
        errors.append({"code": code, "reference": reference})

    if evidence.fixture_hash != digest(scenario.fixture.model_dump(mode="json")):
        error("fixture_hash_mismatch", "initial")
    if evidence.seed_hash != digest(from_scenario(scenario).model_dump(mode="json")):
        error("seed_hash_mismatch", "initial")
    if evidence.initial_hash != digest(evidence.initial_full):
        error("initial_state_hash_mismatch", "initial_full")
    execution = evidence.execution
    catalog_names = [tool["name"] for tool in evidence.catalog]
    if not set(scenario.tools.available) <= set(catalog_names) or len(set(catalog_names)) != len(
        catalog_names
    ):
        error("missing_or_conflicting_tool_catalog", "catalog")
    if execution[
        "task"
    ] != scenario.user_request or evidence.tool_access != scenario.tools.model_dump(mode="json"):
        error("scenario_execution_binding_mismatch", "execution")
    config = execution["config"]
    if (config["actor_id"], config["tenant_id"], config["sandbox_run_id"]) != (
        scenario.actor.actor_id,
        scenario.actor.tenant_id,
        evidence.sandbox_run_id,
    ) or execution["context"] != {"marker": evidence.marker, "seed_hash": evidence.seed_hash}:
        error("execution_context_mismatch", "execution")
    if execution["execution_id"] != evidence.execution_id:
        error("execution_id_mismatch", "execution")
    sequences = [event["sequence"] for event in evidence.events]
    if sequences != list(range(1, execution["journal_seq"] + 1)):
        error("journal_sequence_gap", "events")
    index = {}
    for event in evidence.events:
        payload = event["payload"]
        if (
            event["execution_id"] != evidence.execution_id
            or payload.get("correlation_id") != evidence.execution_id
        ):
            error("event_correlation_mismatch", f"events/{event['sequence']}")
        key = (
            event["event_type"],
            payload.get("attempt_id") or payload.get("tool_call_id") or payload.get("request_id"),
        )
        index.setdefault(key, []).append(event)
    if execution["status"] not in {"prepared", "running"} and not any(
        event["event_type"] in {"run_completed", "run_failed", "run_interrupted"}
        for event in evidence.events
    ):
        error("missing_terminal_event", "events")
    if execution["tool_calls"] != len(evidence.attempts):
        error("attempt_counter_mismatch", "attempts")
    if execution["llm_calls"] != len(evidence.requests):
        error("model_counter_mismatch", "requests")
    operations = {op["proposal_id"]: op for op in evidence.operations}
    proposed = {}
    for request in evidence.requests:
        for position, call in enumerate(request["calls"]):
            key = (request["turn"], position)
            if key in proposed:
                error("conflicting_model_proposals", "requests")
            proposed[key] = call
    if len(operations) != len(evidence.operations):
        error("duplicate_proposal_identity", "operations")
    logical = [op["operation_id"] for op in evidence.operations if op["operation_id"]]
    if len(logical) != len(set(logical)):
        error("duplicate_logical_identity", "operations")
    for op in evidence.operations:
        ref = f"operations/{op['proposal_id']}"
        model_call = proposed.get((op["turn"], op["position"]))
        if model_call is None or (model_call["name"], model_call["call_id"]) != (
            op["tool"],
            op["model_call_id"],
        ):
            error("proposal_model_correlation_mismatch", ref)
        elif op["status"] != "rejected":
            try:
                if not same(json.loads(model_call["arguments_json"]), op["arguments"]):
                    error("model_intent_arguments_conflict", ref)
            except ValueError:
                error("model_intent_arguments_conflict", ref)
        if op["arguments_hash"] != digest(op["arguments"]):
            error("intent_argument_hash_mismatch", ref)
        response = op.get("response")
        if op["status"] == "succeeded" and (
            response is None or response.get("error") is not None or response.get("data") is None
        ):
            error("successful_operation_response_conflict", ref)
        if response and response.get("provenance"):
            provenance = response["provenance"]
            if (
                provenance.get("seed_hash"),
                provenance.get("fixture_id"),
                provenance.get("tool"),
                provenance.get("source"),
                provenance.get("trust_classification"),
            ) != (
                evidence.seed_hash,
                scenario.fixture.fixture_id,
                op["tool"],
                "opsdesk",
                "untrusted",
            ):
                error("tool_provenance_context_mismatch", ref)
        if ("tool_call_proposed", op["proposal_id"]) not in index:
            error("missing_proposal_event", ref)
        if op["status"] == "rejected" and ("tool_call_rejected", op["proposal_id"]) not in index:
            error("missing_rejection_event", ref)
    for attempt in evidence.attempts:
        ref = f"attempts/{attempt['attempt_id']}"
        op = operations.get(attempt["proposal_id"])
        if op is None:
            error("orphan_attempt", ref)
            continue
        started = index.get(("tool_call_started", attempt["attempt_id"]), [])
        if len(started) != 1 or started[0]["payload"].get("tool_call_id") != op["proposal_id"]:
            error("missing_or_conflicting_attempt_event", ref)
        if attempt["status"] != "started":
            kind = "tool_call_succeeded" if attempt["status"] == "succeeded" else "tool_call_failed"
            if len(index.get((kind, attempt["attempt_id"]), [])) != 1:
                error("missing_attempt_completion", ref)
    for request in evidence.requests:
        if ("model_request", request["request_id"]) not in index:
            error("missing_model_request", f"requests/{request['request_id']}")
        if (
            request["status"] == "completed"
            and ("model_response", request["request_id"]) not in index
        ):
            error("missing_model_response", f"requests/{request['request_id']}")

    committed = {}
    used_receipts, used_audits = set(), set()
    for op in evidence.operations:
        if op["tool"] not in {"create_task", "update_task"} or not op["operation_id"]:
            continue
        identity = {
            "run": evidence.sandbox_run_id,
            "actor": scenario.actor.actor_id,
            "tenant": scenario.actor.tenant_id,
            "tool": op["tool"],
            "operation": op["operation_id"],
        }
        key = receipt_key(identity)
        receipts = [
            (i, receipt)
            for i, receipt in enumerate(evidence.receipts)
            if receipt["idempotency_key"] == key
            and receipt["operation"] == op["tool"]
            and receipt["actor_id"] == scenario.actor.actor_id
            and receipt["tenant_id"] == scenario.actor.tenant_id
        ]
        if not receipts:
            if op["status"] == "succeeded":
                error("successful_write_missing_receipt", f"operations/{op['proposal_id']}")
            continue
        if len(receipts) != 1:
            error("conflicting_receipts", f"operations/{op['proposal_id']}")
            continue
        i, receipt = receipts[0]
        try:
            model = CreateTaskInput if op["tool"] == "create_task" else UpdateTaskInput
            fingerprint = digest(model.model_validate(op["arguments"]).model_dump(mode="json"))
        except (ValidationError, ValueError):
            fingerprint = None
        if fingerprint != receipt["request_hash"]:
            error("receipt_argument_conflict", f"receipts/{i}")
            continue
        matching = [
            audit
            for audit in evidence.audits
            if audit["operation"] == receipt["operation"]
            and audit["tenant_id"] == receipt["tenant_id"]
            and audit["actor_id"] == receipt["actor_id"]
            and normalized_task(audit["after"]) == normalized_task(receipt["response"])
        ]
        if len(matching) != 1:
            error("missing_or_conflicting_mutation_audit", f"receipts/{i}")
            continue
        audit = matching[0]
        response = op.get("response")
        if (
            response
            and response.get("data")
            and any(
                response["data"].get(key) != receipt["response"].get(key)
                for key in ("task_id", "version", "status")
            )
        ):
            error("receipt_response_conflict", f"operations/{op['proposal_id']}")
        committed[op["operation_id"]] = {
            "proposal_id": op["proposal_id"],
            "audit_sequence": audit["sequence"],
            "receipt_key": key,
        }
        used_receipts.add(i)
        used_audits.add(audit["sequence"])
    if len(used_receipts) != len(evidence.receipts):
        error("unmatched_receipt", "receipts")
    if len(used_audits) != len(evidence.audits):
        error("unmatched_mutation_audit", "audits")

    expected_full = copy.deepcopy(evidence.initial_full)
    for number, audit in enumerate(evidence.audits, 1):
        task_id = audit["task_id"]
        before = expected_full["tasks"].get(task_id)
        if audit["sequence"] != number:
            error("mutation_sequence_gap", f"audits/{audit['sequence']}")
        if (before is None) != (audit["before"] is None) or (
            before is not None and normalized_task(before) != normalized_task(audit["before"])
        ):
            error("audit_chain_conflict", f"audits/{audit['sequence']}")
        if audit["after"].get("task_id") != task_id:
            error("audit_target_conflict", f"audits/{audit['sequence']}")
        expected_full["tasks"][task_id] = {
            **normalized_task(audit["after"]),
            "tenant_id": audit["tenant_id"],
        }
    unexplained = changes(expected_full, evidence.final_full, entities=tuple(evidence.initial_full))
    if not same(expected_full, evidence.final_full):
        error("unexplained_full_state_mutation", "final_full")
    return {
        "complete": not errors,
        "errors": errors,
        "committed": committed,
        "mutation_count": len(evidence.audits),
        "unexplained_changes": unexplained,
        "journal_reference": f"opsdesk-agent://executions/{evidence.execution_id}/journal",
        "journal_high_water": execution["journal_seq"],
        "source_hashes": evidence.source_hashes,
    }
