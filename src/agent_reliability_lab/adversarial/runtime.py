"""Trusted host interceptor around actual MCP calls; no server/authentication changes."""

import copy
import json

from agent_reliability_lab.adversarial.triggers import fires, matching_ordinal, subset
from agent_reliability_lab.opsdesk.fixtures import digest


def contains_text(value, text):
    if isinstance(value, str):
        return text in value
    if isinstance(value, dict):
        return any(contains_text(v, text) for v in value.values())
    if isinstance(value, list):
        return any(contains_text(v, text) for v in value)
    return False


def failure(code, retryable=False):
    return {
        "source": "agent_transport",
        "data": None,
        "error": {
            "code": code,
            "message": "Controlled synthetic tool failure.",
            "retryable": retryable,
        },
    }


class Interceptor:
    def __init__(self, store, execution_id, plan, clock):
        self.store, self.execution_id, self.plan, self.clock = store, execution_id, plan, clock

    def emit(self, kind, spec, op, attempt_id, **values):
        self.store.event(
            self.execution_id,
            kind,
            self.clock(),
            injection_id=spec.injection_id,
            configuration_hash=digest(spec.model_dump(mode="json")),
            tool_call_id=op["proposal_id"],
            logical_operation_id=op["operation_id"],
            attempt_id=attempt_id,
            tool=op["tool"],
            **values,
        )

    async def call(self, session, tool, op, attempt_id):
        active = None
        for spec in [*self.plan.faults, *self.plan.attacks]:
            if spec.tool != op["tool"] or not subset(spec.trigger.arguments, op["arguments"]):
                continue
            ordinal = matching_ordinal(self.store, self.execution_id, spec)
            matched = fires(spec.trigger, ordinal)
            self.emit(
                "injection_trigger", spec, op, attempt_id, matched=matched, dispatch_ordinal=ordinal
            )
            if matched:
                active = spec
        if active is None:
            return await session.call(tool, op["arguments"], op["operation_id"])
        is_fault = hasattr(active, "fault_type")
        boundary = active.boundary if is_fault else "before_output_validation"
        if boundary == "before_dispatch":
            self.emit(
                "injection_activated",
                active,
                op,
                attempt_id,
                boundary=boundary,
                underlying_executed=False,
                underlying_success=False,
            )
            code = {
                "transient_error": "database_unavailable",
                "timeout_before_dispatch": "tool_timeout",
                "permanent_error": active.permanent_code,
            }[active.fault_type]
            return failure(code, active.fault_type != "permanent_error")

        transformed = False

        def transform(payload):
            nonlocal transformed
            # Never turn denied/error observations into successful attacker content.
            if not isinstance(payload, dict) or payload.get("error") is not None:
                return payload
            result = copy.deepcopy(payload)
            if is_fault:
                if active.fault_type == "malformed_response":
                    result = {"controlled_invalid_payload": True}
                elif active.fault_type == "empty_result":
                    result["data"] = {"items": [], "next_after_id": None}
                else:
                    return payload
            else:
                components = active.surface.strip("/").split("/")
                parent = result
                try:
                    for component in components[:-1]:
                        parent = (
                            parent[int(component)]
                            if isinstance(parent, list)
                            else parent[component]
                        )
                    key = components[-1]
                    if not isinstance(parent[key], str):
                        return payload
                    parent[key] += "\n" + active.payload
                except (KeyError, IndexError, TypeError):
                    return payload
            self.emit(
                "injection_activated",
                active,
                op,
                attempt_id,
                boundary=boundary,
                underlying_executed=True,
                underlying_success=True,
                original_response_hash=digest(payload),
                transformed_response_hash=digest(result),
            )
            transformed = True
            return result

        response = await session.call(
            tool,
            op["arguments"],
            op["operation_id"],
            transform=transform if boundary == "before_output_validation" else None,
        )
        if boundary == "after_validated_response" and response.get("error") is None:
            self.emit(
                "injection_activated",
                active,
                op,
                attempt_id,
                boundary=boundary,
                underlying_executed=True,
                underlying_success=True,
                original_response_hash=digest(response),
            )
            return failure("transport_unavailable", True)
        if not transformed:
            self.emit(
                "injection_not_applied",
                active,
                op,
                attempt_id,
                reason="underlying_error_or_missing_textual_surface",
            )
        return response

    def observed(self, op, attempt_id, response):
        specs = {s.injection_id: s for s in [*self.plan.faults, *self.plan.attacks]}
        for event in self.store.trace(self.execution_id):
            item = event["payload"]
            if event["event_type"] != "injection_activated" or item.get("attempt_id") != attempt_id:
                continue
            spec = specs[item["injection_id"]]
            self.emit(
                "injection_observed",
                spec,
                op,
                attempt_id,
                observed_response_hash=digest(response),
                error_code=(response.get("error") or {}).get("code"),
                payload_delivered=not hasattr(spec, "fault_type")
                and contains_text(response, spec.payload),
            )

    def model_exposure(self, messages, request_id, input_hash):
        # Verify exact payload in a *tool* message tied to the affected proposal.
        # Evidence references are committed before invoking the model; completed/failed
        # request records later determine whether provider delivery is known.
        trace = self.store.trace(self.execution_id)
        proposals = {
            event["payload"]["tool_call_id"]: event["payload"]
            for event in trace
            if event["event_type"] == "tool_call_proposed"
        }
        for spec in [*self.plan.faults, *self.plan.attacks]:
            is_fault = hasattr(spec, "fault_type")
            for event in trace:
                item = event["payload"]
                if (
                    event["event_type"] != "injection_observed"
                    or item.get("injection_id") != spec.injection_id
                ):
                    continue
                if not is_fault and not item.get("payload_delivered"):
                    continue
                proposal = proposals[item["tool_call_id"]]
                operation = self.store.operation(proposal["tool_call_id"])
                seen = False
                for message in messages:
                    if (
                        message.get("role") != "tool"
                        or message.get("tool_call_id") != operation["model_call_id"]
                    ):
                        continue
                    value = json.loads(message.get("content", "{}"))
                    observation = value.get("observation", value)
                    seen = seen or (
                        digest(observation) == item["observed_response_hash"]
                        if is_fault
                        else contains_text(value, spec.payload)
                    )
                if seen:
                    self.emit(
                        "injection_model_exposure",
                        spec,
                        operation,
                        item["attempt_id"],
                        request_id=request_id,
                        input_hash=input_hash,
                        observed_response_hash=item["observed_response_hash"],
                    )
