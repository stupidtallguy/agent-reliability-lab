"""Verify configuration -> activation -> observation -> completed model request links."""

from agent_reliability_lab.adversarial.contracts import HarnessSpec
from agent_reliability_lab.adversarial.triggers import fires, subset
from agent_reliability_lab.evaluation.contracts import Evidence
from agent_reliability_lab.opsdesk.fixtures import digest


def verify(evidence: Evidence) -> tuple[HarnessSpec, list[dict], list[str]]:
    context = evidence.experimental
    harness = HarnessSpec.model_validate(context["harness"])
    errors, records = [], []
    runtime = harness.runtime()
    expected = digest(runtime.model_dump(mode="json"))
    if (
        context["harness_hash"] != digest(harness.model_dump(mode="json"))
        or context["runtime_hash"] != expected
        or digest(evidence.execution["config"].get("runtime_plan")) != expected
        or context["defense"] != evidence.execution["config"].get("defense")
    ):
        errors.append("experimental_configuration_mismatch")
    attempts = {a["attempt_id"]: a for a in evidence.attempts}
    operations = {o["proposal_id"]: o for o in evidence.operations}
    requests = {r["request_id"]: r for r in evidence.requests}
    identities = {s.injection_id for s in [*runtime.faults, *runtime.attacks]}
    if any(
        e["event_type"].startswith("injection_")
        and e["payload"].get("injection_id") not in identities
        for e in evidence.events
    ):
        errors.append("unknown_injection_identity")
    for spec in [*runtime.faults, *runtime.attacks]:
        is_fault = hasattr(spec, "fault_type")
        events = [
            e for e in evidence.events if e["payload"].get("injection_id") == spec.injection_id
        ]
        if any(
            e["payload"].get("configuration_hash") != digest(spec.model_dump(mode="json"))
            for e in events
        ):
            errors.append(f"injection_specification_hash_mismatch:{spec.injection_id}")
        activated = [e for e in events if e["event_type"] == "injection_activated"]
        matching_attempts = [
            a
            for a in evidence.attempts
            if operations.get(a["proposal_id"], {}).get("tool") == spec.tool
            and subset(spec.trigger.arguments, operations[a["proposal_id"]]["arguments"])
        ]
        for ordinal, attempt in enumerate(matching_attempts, 1):
            triggers = [
                e
                for e in events
                if e["event_type"] == "injection_trigger"
                and e["payload"].get("attempt_id") == attempt["attempt_id"]
            ]
            if (
                len(triggers) != 1
                or triggers[0]["payload"].get("dispatch_ordinal") != ordinal
                or triggers[0]["payload"].get("matched") != fires(spec.trigger, ordinal)
            ):
                errors.append(
                    f"missing_or_invalid_trigger:{spec.injection_id}:{attempt['attempt_id']}"
                )
        if len(activated) > spec.trigger.max_activations:
            errors.append(f"activation_limit_exceeded:{spec.injection_id}")
        for event in activated:
            item = event["payload"]
            aid = item.get("attempt_id")
            attempt = attempts.get(aid)
            op = operations.get(item.get("tool_call_id"))
            valid = bool(
                attempt
                and op
                and attempt["proposal_id"] == op["proposal_id"]
                and op["tool"] == spec.tool
                and item.get("logical_operation_id") == op["operation_id"]
            )
            triggers = [
                e
                for e in events
                if e["event_type"] == "injection_trigger"
                and e["payload"].get("attempt_id") == aid
                and e["payload"].get("matched") is True
            ]
            observations = [
                e
                for e in events
                if e["event_type"] == "injection_observed" and e["payload"].get("attempt_id") == aid
            ]
            completed = [
                e
                for e in evidence.events
                if e["event_type"] in {"tool_call_succeeded", "tool_call_failed"}
                and e["payload"].get("attempt_id") == aid
            ]
            valid = valid and len(triggers) == len(observations) == len(completed) == 1
            if valid:
                valid = triggers[0]["sequence"] < event["sequence"] < observations[0][
                    "sequence"
                ] < completed[0]["sequence"] and observations[0]["payload"].get(
                    "observed_response_hash"
                ) == completed[0]["payload"].get("response_hash")
                if not is_fault and observations[0]["payload"].get("payload_delivered"):
                    valid = valid and item.get("transformed_response_hash") == observations[0][
                        "payload"
                    ].get("observed_response_hash")
            model_events = [
                e
                for e in events
                if e["event_type"] == "injection_model_exposure"
                and e["payload"].get("attempt_id") == aid
            ]
            seen_model = False
            delivery_unknown = False
            for model_event in model_events:
                p = model_event["payload"]
                request = requests.get(p.get("request_id"))
                if (
                    not observations
                    or not request
                    or p.get("observed_response_hash")
                    != observations[0]["payload"].get("observed_response_hash")
                    or (not is_fault and not observations[0]["payload"].get("payload_delivered"))
                    or not any(
                        e["event_type"] == "model_request"
                        and e["payload"].get("request_id") == request["request_id"]
                        and e["payload"].get("input_hash") == p.get("input_hash")
                        for e in evidence.events
                    )
                ):
                    valid = False
                elif request["status"] == "completed":
                    seen_model = True
                else:
                    delivery_unknown = True
            if (
                not is_fault
                and observations
                and observations[0]["payload"].get("payload_delivered")
                and not model_events
                and any(
                    e["event_type"] == "model_request"
                    and e["sequence"] > observations[0]["sequence"]
                    for e in evidence.events
                )
            ):
                valid = False
            model_exposed = None if delivery_unknown and not seen_model else seen_model
            if is_fault and not model_events:
                # Older captures did not instrument fault-to-model visibility.
                if not context.get("model_visibility_capture"):
                    model_exposed = None
                elif (
                    observations
                    and op
                    and (op.get("response") or {}).get("response_hash")
                    == observations[0]["payload"].get("observed_response_hash")
                    and any(request["turn"] > op["turn"] for request in evidence.requests)
                ):
                    valid = False
            if not valid:
                errors.append(f"incomplete_exposure_chain:{spec.injection_id}:{aid}")
            records.append(
                {
                    "injection_id": spec.injection_id,
                    "kind": "fault" if is_fault else "attack",
                    "type": spec.fault_type if is_fault else "indirect_prompt_injection",
                    "configuration_hash": digest(spec.model_dump(mode="json")),
                    "attempt_id": aid,
                    "proposal_id": item.get("tool_call_id"),
                    "logical_operation_id": item.get("logical_operation_id"),
                    "boundary": item.get("boundary"),
                    "activated": True,
                    "observation_delivered": bool(valid),
                    "model_exposed": model_exposed if valid else None,
                    "exposed": (
                        True if is_fault and spec.visibility == "agent_transport" else model_exposed
                    )
                    if valid
                    else None,
                    "expected_visibility": spec.visibility if is_fault else "model_observation",
                    "underlying_executed": item.get("underlying_executed") if valid else None,
                    "underlying_success": item.get("underlying_success") if valid else None,
                    "source_sequence": event["sequence"],
                    "recoverable": spec.recoverable if is_fault else False,
                }
            )
        # Missing activation after a matched trigger is inconclusive, not unexposed.
        for orphan in events:
            if orphan["event_type"] in {
                "injection_observed",
                "injection_model_exposure",
            } and not any(
                event["payload"].get("attempt_id") == orphan["payload"].get("attempt_id")
                for event in activated
            ):
                errors.append(f"orphan_exposure_stage:{spec.injection_id}")
        for event in events:
            if event["event_type"] == "injection_trigger" and event["payload"].get("matched"):
                aid = event["payload"].get("attempt_id")
                if not any(e["payload"].get("attempt_id") == aid for e in activated):
                    # A denied underlying call or unavailable response field can legitimately
                    # prevent injection. A durable completed attempt proves this opportunity ended.
                    if not any(
                        e["event_type"] == "injection_not_applied"
                        and e["payload"].get("attempt_id") == aid
                        for e in evidence.events
                    ):
                        errors.append(
                            f"matched_trigger_without_activation:{spec.injection_id}:{aid}"
                        )
        if not activated:
            records.append(
                {
                    "injection_id": spec.injection_id,
                    "kind": "fault" if is_fault else "attack",
                    "type": spec.fault_type if is_fault else "indirect_prompt_injection",
                    "activated": False,
                    "exposed": None if any(spec.injection_id in e for e in errors) else False,
                    "model_exposed": False,
                    "reason": "trigger_or_surface_not_reached",
                }
            )
    return harness, records, errors
