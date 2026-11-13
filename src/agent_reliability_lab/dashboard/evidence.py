"""Readable, read-only views of the frozen execution and attack evidence."""

import streamlit as st

from agent_reliability_lab.dashboard.design import (
    bar_chart,
    bounded,
    exact_refs,
    fields,
    html,
    metric_cards,
    plain,
    short_ref,
    status_text,
    timestamp,
    title_case,
)

EVENT_LABELS = {
    "run_started": ("Execution started", "Started", "info"),
    "run_resumed": ("Execution resumed", "Resumed", "pending"),
    "run_interrupted": ("Execution interrupted", "Incomplete", "pending"),
    "model_request": ("Model request", "Requested", "info"),
    "model_response": ("Model decision", "Received", "good"),
    "model_failed": ("Model request", "Failed", "bad"),
    "tool_call_proposed": ("Tool proposal", "Proposed", "info"),
    "tool_call_rejected": ("Validation", "Rejected", "bad"),
    "tool_call_started": ("MCP dispatch", "Attempt started", "info"),
    "tool_call_succeeded": ("Tool response", "Succeeded", "good"),
    "tool_call_failed": ("Tool response", "Failed", "bad"),
    "retry_scheduled": ("Retry scheduled", "Retrying", "pending"),
    "injection_trigger": ("Injection trigger checked", "Checked", "info"),
    "injection_activated": ("Injection activated", "Activated", "pending"),
    "injection_not_applied": ("Injection not applied", "Not applied", "neutral"),
    "injection_observed": ("Tool observation captured", "Captured", "info"),
    "injection_model_exposure": ("Model-visible observation", "Exposure recorded", "pending"),
    "defense_block": ("Guarded defense", "Blocked", "bad"),
    "budget_exhausted": ("Execution budget", "Exhausted", "bad"),
    "run_completed": ("Agent final outcome", "Agent completed", "good"),
    "run_failed": ("Agent final outcome", "Agent stopped", "bad"),
}


def timeline_rows(evidence):
    requests = {r["request_id"]: r for r in evidence.get("requests", []) if "request_id" in r}
    attempts = {a["attempt_id"]: a for a in evidence.get("attempts", []) if "attempt_id" in a}
    for event in evidence.get("events", []):
        kind = event.get("event_type")
        payload = event.get("payload", {})
        name, status, tone = EVENT_LABELS.get(kind, (title_case(kind), "Recorded", "neutral"))
        if payload.get("error_code") in {"permission_denied", "approval_required"}:
            status, tone = "Denied", "bad"
        if kind == "model_response":
            duration = requests.get(payload.get("request_id"), {}).get("duration_ms")
        elif kind in {"tool_call_succeeded", "tool_call_failed"}:
            duration = attempts.get(payload.get("attempt_id"), {}).get("duration_ms")
        else:
            duration = None
        seq = event.get("sequence")
        details = [f"#{plain(seq)}", timestamp(event.get("timestamp"))]
        if payload.get("tool"):
            details.append(payload["tool"])
        if duration is not None:
            details.append(f"{duration:.0f} ms duration")
        if payload.get("error_code"):
            details.append(title_case(payload["error_code"]))
        if payload.get("effect"):
            details.append(f"Effect: {title_case(payload['effect'])}")
        if payload.get("correlation_id"):
            details.append(f"Correlation {short_ref(payload['correlation_id'])}")
        if seq is not None:
            details.append(f"events/{seq}")
        yield name, status, tone, " · ".join(details)


def timeline(rows):
    items = "".join(
        '<li><div class="lab-timeline-title">'
        f'<strong>{html(name)}</strong><span class="lab-status {html(tone)}">{html(status)}</span>'
        f'</div><span class="lab-timeline-meta">{html(details)}</span></li>'
        for name, status, tone, details in rows
    )
    st.html(f'<ol class="lab-timeline" role="list" aria-label="Execution timeline">{items}</ol>')


def select_trial(view, document, *, security=False):
    choices = sorted(document["results"], key=lambda row: (row["scenario_id"], row["trial_index"]))
    if security:
        focus = st.selectbox("Trial group", ["Security and fault trials", "All report trials"])
        if focus == "Security and fault trials":
            choices = [
                t
                for t in choices
                if (t.get("experimental") or {}).get("case_kind") in {"attack", "fault", "mixed"}
            ]
    if not choices:
        st.info(
            "No matching materialized trials on this report. Choose another report or trial group."
        )
        return None, None
    selected = st.selectbox(
        "Trial",
        choices,
        format_func=lambda t: f"{t['scenario_id']} · trial {t.get('trial_index', '—')}",
        key=f"trial_{security}_{document['report_id']}",
    )
    return view.trial(selected["trial_id"]), selected


def execution_trace(view, document):
    trial, score = select_trial(view, document)
    if trial is None:
        return
    evidence = trial.get("evidence")
    fields(
        [
            ("Agent status", title_case(score.get("agent_status"))),
            (
                "Objective task success",
                status_text(
                    score.get("objective_success"), yes="Verified success", no="Verified failure"
                ),
            ),
            (
                "Tool proposals / attempts",
                f"{plain(score.get('tool_proposals'))} / {plain(score.get('tool_attempts'))}",
            ),
            ("Execution ID", short_ref(score.get("execution_id"))),
        ]
    )
    exact_refs(
        [
            ("Execution ID", score.get("execution_id")),
            ("Trial ID", trial.get("trial_id")),
            ("Evidence reference", score.get("evidence_reference")),
        ],
        label="Exact execution and evidence references",
    )
    if not isinstance(evidence, dict):
        st.info("Frozen execution evidence is unavailable for this trial.")
        return
    st.subheader("Execution timeline", anchor=False)
    rows = list(timeline_rows(evidence))
    if rows:
        timeline(rows)
        correlations = dict.fromkeys(
            event.get("payload", {}).get("correlation_id") for event in evidence.get("events", [])
        )
        if any(correlations):
            exact_refs(
                [(short_ref(value), value) for value in correlations if value],
                label="Exact timeline correlation IDs",
            )
    else:
        st.info("This capture contains no journal events.")
    st.subheader("Reconciliation and final outcome", anchor=False)
    fields(
        [
            (
                "Receipts recorded",
                len(evidence["receipts"]) if isinstance(evidence.get("receipts"), list) else None,
            ),
            (
                "Audit entries recorded",
                len(evidence["audits"]) if isinstance(evidence.get("audits"), list) else None,
            ),
            (
                "Prohibited effect",
                status_text(score.get("unsafe"), yes="Verified effect", no="No verified effect"),
            ),
        ]
    )
    findings = score.get("findings", [])
    if findings:
        st.dataframe(
            bounded(
                [
                    {
                        "Finding": title_case(f.get("label")),
                        "Evidence": ", ".join(f.get("references", [])),
                    }
                    for f in findings
                ]
            ),
            hide_index=True,
        )
    execution = evidence.get("execution") or {}
    result = execution.get("result") or {}
    if result.get("answer"):
        with st.expander("Agent response"):
            st.text(bounded(result["answer"]))
    for label, keys in (
        ("Sanitized requests and model decisions", ("requests",)),
        ("Validated operations, attempts and responses", ("operations", "attempts")),
        ("Receipts, audits and logical state", ("receipts", "audits", "initial", "final")),
        ("Sealed journal and evaluation diagnostics", ("provenance", "events")),
    ):
        with st.expander(label):
            st.json(
                bounded(
                    {key: evidence.get(key) for key in keys}
                    | (
                        {"reconciliation": score.get("reconciliation"), "findings": findings}
                        if "events" in keys
                        else {}
                    )
                )
            )


def observed(records, key):
    values = [record.get(key) for record in records]
    if any(value is True for value in values):
        return True
    return False if values and all(value is False for value in values) else None


def attack_flow(trial, score):
    exp = score.get("experimental") or {}
    planned = exp.get("planned_trial") or {}
    objectives = exp.get("objectives", [])
    exposures = exp.get("exposures", [])
    if not objectives and not exposures and planned.get("attack_count") is None:
        st.info("Attack plan and exposure evidence are unavailable for this trial.")
        return
    stage_rows = []
    for goal in objectives:
        injection_id = goal.get("injection_id")
        matching = [e for e in exposures if e.get("injection_id") == injection_id]

        attribution = goal.get("attribution") or {}
        links = attribution.get("matched_proposal_ids") or []
        stage_rows.append(
            {
                "Injection": injection_id,
                "Objective": title_case(goal.get("objective")),
                "Activated": status_text(observed(matching, "activated")),
                "Delivered": status_text(observed(matching, "observation_delivered")),
                "Model exposure": status_text(
                    goal.get("verified_exposure")
                    if score.get("evaluator_version") == "1.7.0"
                    else goal.get("verified_exposure", goal.get("exposed"))
                ),
                "Matched proposals": len(links) if "matched_proposal_ids" in attribution else None,
                "Post-exposure candidates": sum(
                    candidate.get("eligible") is True
                    for candidate in attribution.get("candidates", [])
                )
                if "candidates" in attribution
                else None,
                "Attribution": title_case(attribution.get("status")),
                "Objective achieved": status_text(goal.get("success")),
            }
        )
    fields(
        [
            ("Configured payloads", planned.get("attack_count")),
            ("Unauthorized proposal", status_text(score.get("unauthorized_attempt"))),
            ("Prohibited executed effect", status_text(score.get("unsafe"))),
            (
                "Trial attack outcome",
                status_text(
                    score.get("attacker_success"), yes="Verified success", no="Verified non-success"
                ),
            ),
        ]
    )
    if stage_rows:
        st.subheader("Attack evidence chain", anchor=False)
        choices = [r["Injection"] for r in stage_rows]
        selected = st.selectbox("Injection", choices) if len(choices) > 1 else choices[0]
        row = next(r for r in stage_rows if r["Injection"] == selected)
        stages = [
            ("Configured", row["Objective"]),
            ("Activated", row["Activated"]),
            ("Delivered", row["Delivered"]),
            ("Model exposure", row["Model exposure"]),
            ("Operation candidates", row["Post-exposure candidates"]),
            ("Attribution", row["Attribution"]),
            ("Objective achieved", row["Objective achieved"]),
        ]
        items = "".join(
            f"<li><strong>{html(label)}</strong><span>{html(value)}</span></li>"
            for label, value in stages
        )
        st.html(f'<ol class="lab-flow" role="list" aria-label="Attack evidence chain">{items}</ol>')
        st.dataframe(bounded(stage_rows), hide_index=True)
    recoveries = exp.get("recoveries", [])
    if recoveries:
        st.subheader("Recovery evidence", anchor=False)
        st.dataframe(
            bounded(
                [
                    {
                        "Fault": r.get("injection_id"),
                        "Recoverable": status_text(r.get("recoverable")),
                        "Affected attempt": r.get("affected_attempt_id"),
                        "Recovery attempted": status_text(r.get("recovery_attempted")),
                        "Recovery": status_text(r.get("recovered")),
                    }
                    for r in recoveries
                ]
            ),
            hide_index=True,
        )
    st.caption("Temporal eligibility establishes order. Causal influence remains unestablished.")
    with st.expander("Attribution, exposure and fault records"):
        exact_refs(
            [("Evidence reference", score.get("evidence_reference") or trial.get("evidence_hash"))]
        )
        st.json(bounded(exp))


def security(view, document):
    summary = document["summary"]
    security = summary.get("security", {})
    attack = security.get("attack_outcome_coverage", {})
    metrics = summary["metrics"]
    metric_cards(
        [
            (
                "Unauthorized attempt rate",
                metrics.get("unauthorized_action_attempt_rate", {}),
                "Proposals assessed for authorization.",
                "adverse",
            ),
            (
                "Prohibited effect rate",
                metrics.get("unsafe_action_rate", {}),
                "Trials assessed for prohibited committed effects.",
                "adverse",
            ),
            (
                "Attack success rate",
                metrics.get("prompt_injection_attack_success_rate", {}),
                "Verified attacker objectives in the measured cohort.",
                "purple",
            ),
        ],
        document["report_manifest"]["metric_definition_version"],
    )
    fields(
        [
            ("Configured attack trials", attack.get("configured_attack_trials")),
            ("Verified exposed trials", attack.get("exposed_trials")),
            ("Unknown attack outcomes", attack.get("unknown_trials")),
        ]
    )
    if security.get("per_objective"):
        st.subheader("Attack objectives", anchor=False)
        st.dataframe(
            [
                {
                    "Category": title_case(kind),
                    "Achieved": plain(record.get("numerator")),
                    "Determinate": plain(record.get("denominator")),
                }
                for kind, record in sorted(security["per_objective"].items())
            ],
            hide_index=True,
        )
    taxonomy = security.get("fault_taxonomy", {})
    if taxonomy:
        bar_chart(
            [
                (
                    "Fault categories",
                    [(title_case(k), n, n, "blue") for k, n in sorted(taxonomy.items())],
                )
            ],
            label="Observed fault specification counts",
        )
    fields(
        [
            (
                "Defense configuration",
                title_case(((document.get("manifest") or {}).get("config") or {}).get("defense")),
            ),
            ("Recorded defense blocks", security.get("defense_blocks")),
        ]
    )
    st.caption("Open Baseline vs Guarded to compare equivalent security trials.")
    st.subheader("Inspect a trial", anchor=False)
    trial, score = select_trial(view, document, security=True)
    if trial:
        attack_flow(trial, score)
