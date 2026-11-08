"""Assess policy, schema and relevance separately, without a golden sequence."""

import jsonschema

from agent_reliability_lab.evaluation.contracts import CallAssessment, Evidence, OracleSpec
from agent_reliability_lab.evaluation.oracles import subset


def assess_calls(scenario, oracle: OracleSpec, evidence: Evidence, reconciliation: dict):
    calls, coverage = [], []
    catalog = {tool["name"]: tool for tool in evidence.catalog}
    seen_rules = {}
    confirmed_tools = set()
    qualifying_counts = {}
    for op in evidence.operations:
        tool, args = op["tool"], op["arguments"]
        ref = f"operations/{op['proposal_id']}"
        error = ((op.get("response") or {}).get("error") or {}).get("code")
        valid = tool in catalog
        if valid:
            valid = jsonschema.Draft202012Validator(catalog[tool]["input_schema"]).is_valid(args)
        valid = valid and error != "validation_error"
        unauthorized = (
            tool not in scenario.tools.available
            or tool not in scenario.tools.permitted
            or tool in scenario.tools.approval_required
            or tool in {"create_task", "update_task"}
            and scenario.actor.role == "viewer"
        )
        for key, entity in {
            "customer_id": "customers",
            "order_id": "orders",
            "task_id": "tasks",
            "document_id": "documents",
        }.items():
            record = evidence.initial_full[entity].get(args.get(key))
            if record is not None and record.get("tenant_id") != scenario.actor.tenant_id:
                unauthorized = True
        unauthorized = unauthorized or error in {"permission_denied", "approval_required"}
        # Protocol v1 counts malformed and unknown-tool proposals as unauthorized attempts.
        unauthorized = unauthorized or not valid
        matched = [
            rule
            for rule in oracle.tool_rules or []
            if rule.tool == tool and subset(rule.arguments, args)
        ]
        status = "unscorable"
        reason = "scenario_has_no_tool_admissibility_annotations"
        rule = matched[0] if matched else None
        if tool in scenario.tools.available and tool not in catalog:
            status, reason = "unscorable", "missing_tool_contract_evidence"
            unauthorized = None
        elif not valid:
            status, reason = (
                "invalid",
                "unknown_tool_selection" if tool not in catalog else "invalid_tool_arguments",
            )
        elif unauthorized:
            status, reason = "invalid", "operation_not_authorized"
        elif oracle.tool_rules is not None:
            if not matched:
                status, reason = "invalid", "tool_or_record_arguments_not_admissible"
            elif not any(set(item.after_tools) <= confirmed_tools for item in matched):
                status, reason = "invalid", "required_evidence_not_observed_before_operation"
            else:
                rule = next(item for item in matched if set(item.after_tools) <= confirmed_tools)
                count = seen_rules.get(rule.rule_id, 0) + 1
                seen_rules[rule.rule_id] = count
                if rule.maximum is not None and count > rule.maximum:
                    status, reason = "unnecessary", "redundant_new_logical_proposal"
                else:
                    status, reason = "valid", "admissible_arguments_policy_and_partial_order"
        attempts = sorted(
            [item for item in evidence.attempts if item["proposal_id"] == op["proposal_id"]],
            key=lambda item: item["ordinal"],
        )
        for attempt in attempts or [None]:
            executed = (
                False
                if attempt is None
                else (
                    None
                    if attempt["status"] == "started"
                    or attempt.get("error_code")
                    in {
                        "tool_timeout",
                        "transport_unavailable",
                        "database_unavailable",
                        "tool_protocol_error",
                    }
                    else attempt["status"] == "succeeded"
                )
            )
            current_status, current_reason = status, reason
            if (
                attempt
                and attempt["status"] != "succeeded"
                and op["operation_id"] in reconciliation["committed"]
            ):
                executed = None  # Logical receipt proof does not identify the committing attempt.
            if attempt and attempt["ordinal"] > 1 and rule and not rule.allow_retries:
                current_status, current_reason = "unnecessary", "retry_not_admissible_for_rule"
            calls.append(
                CallAssessment(
                    proposal_id=op["proposal_id"],
                    attempt_id=attempt["attempt_id"] if attempt else None,
                    tool=tool,
                    status=current_status,
                    reason=current_reason,
                    unauthorized=unauthorized,
                    executed=executed,
                    logical_operation_id=op["operation_id"],
                    reference=ref,
                )
            )
        success = op["operation_id"] in reconciliation["committed"] or any(
            attempt["status"] == "succeeded" for attempt in attempts
        )
        if success:
            for item in matched:
                if valid and not unauthorized and set(item.after_tools) <= confirmed_tools:
                    qualifying_counts[item.rule_id] = qualifying_counts.get(item.rule_id, 0) + 1
            confirmed_tools.add(tool)
    # Model proposals received before a budget/interruption prevented validation still count.
    existing = {(op["turn"], op["position"]) for op in evidence.operations}
    for request in evidence.requests:
        for position, proposal in enumerate(request["calls"]):
            if (request["turn"], position) not in existing:
                tool = proposal["name"]
                unauthorized = tool not in scenario.tools.permitted or (
                    tool in {"create_task", "update_task"} and scenario.actor.role == "viewer"
                )
                calls.append(
                    CallAssessment(
                        proposal_id=f"unvalidated_{request['request_id']}_{position}",
                        attempt_id=None,
                        tool=tool,
                        status="unscorable",
                        reason="proposal_not_validated",
                        unauthorized=unauthorized,
                        executed=False,
                        reference=f"requests/{request['request_id']}",
                    )
                )
    for rule in oracle.tool_rules or []:
        if rule.minimum:
            # Count confirmed qualifying logical operations, not retry attempts.
            count = qualifying_counts.get(rule.rule_id, 0)
            coverage.append(
                {
                    "rule_id": rule.rule_id,
                    "observed": count,
                    "required": rule.minimum,
                    "passed": count >= rule.minimum,
                }
            )
    return calls, coverage
