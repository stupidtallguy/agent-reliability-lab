"""Workspace layouts for stored reports, experiment inventory and paired analyses."""

import json

import streamlit as st

from agent_reliability_lab.dashboard.design import (
    bar_chart,
    bounded,
    fields,
    html,
    metric_cards,
    metric_text,
    plain,
    purpose,
    timestamp,
    title_case,
)
from agent_reliability_lab.evaluation.downloads import render_files
from agent_reliability_lab.opsdesk.fixtures import digest

METRICS = (
    (
        "task_success_rate",
        "Task success rate",
        "Verified tasks per eligible trial. Higher is desirable.",
        "blue",
    ),
    (
        "prompt_injection_attack_success_rate",
        "Attack success rate",
        "Verified attacker outcomes. Lower is desirable.",
        "adverse",
    ),
    (
        "recovery_rate",
        "Fault recovery rate",
        "Successful recoveries after verified exposure.",
        "blue",
    ),
    (
        "coverage",
        "Evidence coverage",
        "Determinate outcomes per exposure-eligible attack slot.",
        "purple",
    ),
    (
        "unauthorized_action_attempt_rate",
        "Unauthorized attempt rate",
        "Trials with unauthorized proposals.",
        "adverse",
    ),
    (
        "unsafe_action_rate",
        "Prohibited effect rate",
        "Trials with prohibited committed effects.",
        "adverse",
    ),
)

PAIR_METRICS = {
    "task_success": "Task success",
    "attack_success": "Attack success",
    "recovery": "Fault recovery",
    "unauthorized_attempt": "Unauthorized attempts",
    "prohibited_effect": "Prohibited effects",
    "defense_false_positive": "Defensive false positives",
}


def overview(document, counts):
    manifest = document.get("manifest") or {}
    summary = document["summary"]
    version = document["report_manifest"]["metric_definition_version"]
    splits = {r.get("split") for r in document["results"]}
    names = {"development": "development", "held_out": "held-out"}
    split_label = ", ".join(sorted({names.get(s, "unavailable") for s in splits})) or "unavailable"
    st.html(
        f'<div class="lab-cohort-label"><strong>{html(purpose(manifest))}</strong>'
        f"<span>Selected trial splits · {html(split_label)}</span></div>"
    )
    attack = summary.get("security", {}).get("attack_outcome_coverage", {})
    metrics = summary["metrics"] | {"coverage": attack.get("coverage", {})}
    metric_cards(
        [
            (label, metrics.get(key, {}), description, tone)
            for key, label, description, tone in METRICS
        ],
        version,
    )
    st.subheader("Outcome distribution", anchor=False)
    outcome_rates = summary.get("outcome_rates", {})
    task = [
        (label, count, count, tone)
        for label, count, tone in [
            ("Verified success", summary.get("successful_count"), "blue"),
            (
                "Verified failure",
                outcome_rates.get("verified_failure", {}).get("numerator"),
                "adverse",
            ),
            ("Unverified", outcome_rates.get("unverified", {}).get("numerator"), "neutral"),
            ("Excluded", summary.get("excluded_count"), "neutral"),
        ]
        if count is not None
    ]
    if task:
        bar_chart(
            [("Task outcomes · selected report trials", task)],
            label="Selected report task outcome counts",
        )
    fields(
        [
            ("Selected trials", summary.get("trial_count")),
            ("Unknown attack outcomes", attack.get("unknown_trials")),
            ("Configured attack trials", attack.get("configured_attack_trials")),
            ("Verified unexposed controls", attack.get("unexposed_controls")),
        ]
    )
    st.caption(
        f"Database inventory · {counts['experiments']} experiments · "
        f"{counts['trials']} trials · {counts['scores']} score revisions"
    )
    with st.expander("Metric definitions and evidence limitations"):
        for key, definition in summary.get("metric_definitions", {}).items():
            st.text(f"{title_case(key)} — {definition}")
        for warning in summary.get("warnings", []):
            st.text(warning)


def matched_report(view, rows, references, side, version):
    trials = {row[side + "_trial_id"] for row in rows if row.get(side + "_trial_id")}
    ids = {r["scoring_id"] for r in references if r["trial_id"] in trials}
    if not trials or len(ids) != len(trials):
        return None
    experiment_id = view.trial(sorted(trials)[0])["experiment_id"]
    for record in view.report_index(experiment_id):
        if record.get("evaluator") != version or set(record["score_ids"]) != ids:
            continue
        return view.report(record["report_id"])
    return None


def comparison(view, scope):
    records = view.rows("artifacts", identifier=scope, kind="analysis", limit=100)
    if not records:
        st.info(
            "This scope has no pinned paired analysis. Open a demo scope or generate an "
            "analysis with the research CLI."
        )
        return
    selected = st.selectbox(
        "Pinned analysis",
        records,
        format_func=lambda r: f"{r['identity']} · revision {r['version']}",
    )
    body = selected["body"]
    result = body["result"]
    if digest(body) != selected["content_hash"] or digest(result) != body["result_hash"]:
        st.error("The saved analysis failed its integrity check. Select another analysis.")
        return
    version = body["evaluator_version"]
    outcomes = result.get("outcomes", {})
    refs, rows = result.get("selected_scores", []), result.get("rows", [])
    reports = {
        side: matched_report(view, rows, refs, side, version) for side in ("baseline", "guarded")
    }
    paired = sum(row.get("verified") is True for row in rows)
    scripted = all(
        doc and (doc.get("manifest") or {}).get("purpose") == "scripted_infrastructure_validation"
        for doc in reports.values()
    )
    fields(
        [
            (
                "Analysis",
                "Verified pairs · descriptive" if paired else "Pairing evidence unavailable",
            ),
            ("Evaluator", version),
            ("Verified pairs", paired),
            ("Data", "Scripted infrastructure" if scripted else "See pinned report provenance"),
        ]
    )
    st.caption(f"{len(result.get('exclusions', []))} excluded pair records in this analysis.")
    chart, table = [], []
    for key, name in PAIR_METRICS.items():
        record = outcomes.get(key)
        if not record:
            continue
        n = record["complete_verified_pairs"]
        left, right = record["baseline_successes"], record["guarded_successes"]
        if not (0 <= n <= paired and 0 <= left <= n and 0 <= right <= n):
            st.error("The saved outcome counts conflict with the verified pair inventory.")
            return
        delta = record.get("paired_risk_difference")
        interval = record.get("cluster_bootstrap_interval")
        if n:
            chart.append(
                (
                    name,
                    [
                        ("Baseline", left / n, f"{left / n:.0%} ({left}/{n})", "blue"),
                        ("Guarded", right / n, f"{right / n:.0%} ({right}/{n})", "purple"),
                    ],
                )
            )
        table.append(
            {
                "Outcome": name,
                "Baseline": f"{left}/{n}" if n else "Unavailable",
                "Guarded": f"{right}/{n}" if n else "Unavailable",
                "Complete pairs": n,
                "Planned in scope": record.get("planned_pairs"),
                "Unknown / incomplete": record.get("incomplete_or_unknown_pairs"),
                "Not applicable": record.get("not_applicable_pairs", 0),
                "Guarded − baseline": f"{delta * 100:+.1f} pp"
                if delta is not None
                else "Unavailable",
                "95% family interval": f"{interval[0]:+.1%} to {interval[1]:+.1%}"
                if interval
                else "Unavailable",
            }
        )
    st.subheader("Paired outcomes", anchor=False)
    if chart:
        bar_chart(
            chart, label="Baseline and Guarded rates on complete verified pairs", percent=True
        )
    else:
        st.info("No outcome has complete eligible pairs in this analysis.")
    if table:
        st.dataframe(table, hide_index=True)
    st.caption("Outcome denominators depend on eligibility. Scripted results are descriptive.")
    st.subheader("Pinned report metrics", anchor=False)
    st.caption("Side-by-side cohort summaries. These measures do not estimate paired effects.")
    extra = []
    for side, document in reports.items():
        if not document:
            continue
        summary = document["summary"]
        accuracy = summary["metrics"].get("tool_call_accuracy", {})
        coverage = summary.get("security", {}).get("attack_outcome_coverage", {})
        latency = summary.get("latency", {})
        cost = summary["metrics"].get("cost_per_successful_task", {})
        extra.append(
            {
                "Configuration": side.title(),
                "Evaluator": version,
                "Tool accuracy": " · ".join(metric_text(accuracy)[:2]),
                "Evidence coverage": " · ".join(metric_text(coverage.get("coverage", {}))[:2]),
                "Unknown outcomes": plain(coverage.get("unknown_trials")),
                "Median latency": f"{latency['median_seconds']:.2f} s (n={latency['count']})"
                if latency.get("median_seconds") is not None
                else "Unavailable",
                "Cost per successful task": f"{cost['value']} {cost.get('currency', 'USD')} "
                f"(n={cost.get('successful_live_tasks')})"
                if cost.get("value") is not None
                else title_case(cost.get("status")),
                "Report ID": document["report_id"],
            }
        )
    if extra:
        st.dataframe(extra, hide_index=True)
    if len(extra) < 2:
        st.info("At least one side lacks a saved report with the exact selected score IDs.")
    with st.expander("Pair exclusions, uncertainty and exact score references"):
        st.json(
            bounded(
                {
                    "exclusions": result.get("exclusions"),
                    "outcomes": outcomes,
                    "scores": refs,
                    "pairs": result.get("pairs"),
                }
            )
        )


def experiments(view, inventory):
    first, second, third = st.columns([2, 1, 1])
    query = first.text_input("Search experiments or scenario IDs", placeholder="e.g. attack_hijack")
    configurations = sorted({r["configuration"] for r in inventory if r.get("configuration")})
    condition = second.selectbox("Configuration", ["All", *configurations], format_func=title_case)
    order = third.selectbox("Sort by", ["Newest", "Oldest", "Most trials"])
    matches = [
        r
        for r in inventory
        if (condition == "All" or r.get("configuration") == condition)
        and query.strip().casefold()
        in " ".join(
            [r["experiment_id"], *(c.get("scenario_id", "") for c in r.get("cases") or [])]
        ).casefold()
    ]
    if order == "Oldest":
        matches.reverse()
    elif order == "Most trials":
        matches.sort(key=lambda r: -(r.get("trial_count") or 0))
    if not matches:
        st.info("No experiments match these filters. Try a different search or configuration.")
        return
    st.caption(f"{len(matches)} experiments on this inventory page")
    st.dataframe(
        bounded(
            [
                {
                    "Experiment": r["experiment_id"],
                    "Status": "Report available" if r.get("has_report") else "No saved report",
                    "Configuration": title_case(r.get("configuration")),
                    "Scenarios": len(r.get("cases") or []),
                    "Trials": r.get("trial_count"),
                    "Evaluator at run": r.get("evaluator"),
                    "Created": timestamp(r.get("created_at")),
                }
                for r in matches
            ]
        ),
        hide_index=True,
    )
    selected = st.selectbox("Inspect experiment", matches, format_func=experiment_label)
    st.subheader("Experiment details", anchor=False)
    fields(
        [
            ("Purpose", purpose(selected)),
            ("Configuration", title_case(selected.get("configuration"))),
            ("Created", timestamp(selected.get("created_at"))),
            ("Manifest SHA-256", selected.get("manifest_hash")),
        ]
    )
    cases = selected.get("cases") or []
    with st.expander("Planned scenario identities", expanded=True):
        if cases:
            st.dataframe(
                bounded(
                    [
                        {
                            "Scenario": c.get("scenario_id"),
                            "Scenario hash": c.get("scenario_hash"),
                            "Validation error": c.get("validation_error"),
                        }
                        for c in cases
                    ]
                ),
                hide_index=True,
            )
        else:
            st.info("No scenario plan is available for this experiment.")
    with st.expander("Materialized trials · first 100"):
        trials = view.rows("trials", identifier=selected["experiment_id"], limit=100)
        st.dataframe(
            bounded(
                [
                    {
                        "Scenario": t.get("scenario_id"),
                        "Trial": t.get("trial_index"),
                        "State": title_case(t.get("state")),
                        "Execution ID": t.get("execution_id"),
                    }
                    for t in trials
                ]
            ),
            hide_index=True,
        )
    with st.expander("Frozen configuration and source metadata"):
        st.json(bounded(view.experiment(selected["experiment_id"])))


def experiment_label(row):
    return f"{title_case(row.get('configuration'))} · {row['experiment_id'][:10]}"


def reports(document, view):
    manifest = document["report_manifest"]
    fields(
        [
            ("Selected score revisions", len(manifest.get("selected_scores", []))),
            ("Saved", timestamp(manifest.get("generated_at"))),
            ("Manifest hash", manifest.get("experiment_manifest_hash")),
        ]
    )
    st.subheader("Download this revision", anchor=False)
    formats = {
        "results.json": ("JSON", "application/json"),
        "metrics.csv": ("CSV", "text/csv"),
        "report.md": ("Markdown", "text/markdown"),
    }
    for column, (name, content) in zip(st.columns(3), render_files(document).items(), strict=True):
        label, mime = formats[name]
        column.download_button(
            f"Download {label}",
            content,
            file_name=name,
            mime=mime,
            on_click="ignore",
            width="stretch",
        )
    st.subheader("Pinned score revisions", anchor=False)
    selected = manifest.get("selected_scores", [])
    if selected:
        st.dataframe(
            bounded(
                [
                    {
                        "Trial": r.get("trial_id"),
                        "Revision": r.get("revision"),
                        "Evaluator": r.get("result_evaluator"),
                        "Score ID": r.get("scoring_id"),
                        "Evidence hash": r.get("evidence_hash"),
                        "Rules hash": r.get("rules_hash"),
                    }
                    for r in selected
                ]
            ),
            hide_index=True,
        )
        with st.expander("Historical score revisions for a trial"):
            trial = st.selectbox("Trial ID", [r["trial_id"] for r in selected])
            revisions = view.rows("scores", identifier=trial, limit=100)
            st.dataframe(
                bounded(
                    [
                        {
                            "Revision": r["revision"],
                            "Evaluator": r["evaluator_version"],
                            "Score ID": r["scoring_id"],
                            "Saved": timestamp(r.get("created_at")),
                            "Result hash": r.get("result_hash"),
                        }
                        for r in revisions
                    ]
                ),
                hide_index=True,
            )
    with st.expander("Exact report manifest and scoring references"):
        st.json(bounded(manifest))


def research(view, scope):
    releases = view.rows("artifacts", identifier=scope, kind="dataset_release", limit=100)
    if releases:
        release = st.selectbox(
            "Dataset release",
            releases,
            format_func=lambda r: f"{r['identity']} · revision {r['version']}",
        )
        body = release["body"]
        if digest(body) != release["content_hash"]:
            st.error("This dataset release failed its integrity check.")
            return
        assignments = body.get("assignments", [])
        fields(
            [
                ("Development scenarios", sum(t["split"] == "development" for t in assignments)),
                ("Held-out scenarios", sum(t["split"] == "held_out" for t in assignments)),
                ("Template families", len({t["family_id"] for t in assignments})),
                ("Dataset hash", release["content_hash"]),
            ]
        )
        st.dataframe(
            bounded(
                [
                    {
                        "Scenario": t.get("scenario_id"),
                        "Partition": title_case(t.get("split")),
                        "Family": t.get("family_id"),
                        "Template": t.get("template_id"),
                    }
                    for t in assignments
                ]
            ),
            hide_index=True,
        )
        if not any(t["split"] == "held_out" for t in assignments):
            st.caption(
                "The held-out partition is empty. This release provides development evidence."
            )
        with st.expander("Dataset release and frozen partition references"):
            st.json(bounded(body))
    else:
        st.info(
            "This scope has no dataset release. The packaged demo includes the development "
            "catalog and its empty held-out partition."
        )
    st.subheader("Study and pairing status", anchor=False)
    pairs = view.rows("artifacts", identifier=scope, kind="pair", limit=100)
    registrations = view.rows("artifacts", identifier=scope, kind="preregistration", limit=100)
    verified = sum(row["body"].get("verification") == "verified" for row in pairs)
    fields(
        [
            ("Verified pair records · first 100", f"{verified} / {len(pairs)}"),
            (
                "Preregistration",
                f"{len(registrations)} saved · first 100"
                if registrations
                else "No registration in this scope",
            ),
        ]
    )
    st.caption(
        "Scripted demonstrations verify infrastructure. Held-out generalization, causal "
        "influence, and live-model reliability require separate evidence."
    )
    if registrations:
        with st.expander("Saved preregistrations"):
            st.json(bounded(registrations))
    with st.expander("Authoring schemas"):
        from agent_reliability_lab.research.contracts import DatasetRelease, Preregistration

        for model in (DatasetRelease, Preregistration):
            st.download_button(
                f"Download {model.__name__} schema",
                json.dumps(model.model_json_schema(), indent=2),
                file_name=model.__name__ + "-schema.json",
                mime="application/json",
                on_click="ignore",
            )
