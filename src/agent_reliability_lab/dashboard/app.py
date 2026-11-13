"""Streamlit entry point. No migrations, scoring, execution or submission actions."""

import json
import os

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from agent_reliability_lab import __version__
from agent_reliability_lab.evaluation.downloads import render_files
from agent_reliability_lab.research.views import ResearchView, readonly_engine

PAGES = [
    "Overview",
    "Baseline vs Guarded",
    "Experiments",
    "Execution traces",
    "Security",
    "Evaluators & reports",
    "Research readiness",
]


@st.cache_resource
def get_view():
    url = os.environ.get("OPSDESK_DASHBOARD_DATABASE_URL")
    return ResearchView(readonly_engine(url)) if url else None


def bounded(value):
    from agent_reliability_lab.agent.journal import Redactor

    value = Redactor().clean(value)
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) > 100_000:
        return {
            "preview_truncated": True,
            "preview": text[:100_000],
            "note": (
                "Full frozen evidence remains in PostgreSQL; this preview is not "
                "an integrity check."
            ),
        }
    return value


def metric(label, record, version):
    value = record.get("value")
    st.metric(label, "Unavailable" if value is None else f"{100 * value:.1f}%")
    st.caption(
        f"Evaluator {version} · {record.get('numerator', 'unknown')} "
        f"/ {record.get('denominator', 'unknown')}"
    )
    if value is None:
        st.caption(record.get("reason") or record.get("status", "unknown"))


def overview(document, counts):
    st.title("Agent Reliability Lab")
    st.caption("Observe actions. Reconcile effects. Measure uncertainty.")
    with st.container(border=True):
        manifest = document.get("manifest")
        manifest = manifest if isinstance(manifest, dict) else {}
        purpose = manifest.get("purpose")
        label = (
            {
                "scripted_infrastructure_validation": "Scripted infrastructure validation",
                "live_evaluation": "Live-model evaluation",
            }.get(purpose, "Experiment purpose unavailable")
            if isinstance(purpose, str)
            else "Experiment purpose unavailable"
        )
        if (
            purpose == "scripted_infrastructure_validation"
            and manifest.get("demonstration") is True
        ):
            label = "Synthetic demonstration"
        splits = {r.get("split") for r in document["results"]}
        splits = {
            "development"
            if s == "development"
            else "held-out"
            if s == "held_out"
            else "unavailable"
            for s in splits
        }
        st.markdown(f"**{label}**")
        st.caption("Selected trial splits · " + (", ".join(sorted(splits)) or "unavailable"))
        st.write(
            "Task completion, attack attribution and committed effects are "
            "separate observations. Candidate results have not received "
            "independent approval."
        )
    version = document["report_manifest"]["metric_definition_version"]
    summary = document["summary"]
    columns = st.columns(3)
    for column, name, label in zip(
        columns,
        ["task_success_rate", "prompt_injection_attack_success_rate", "recovery_rate"],
        ["Task success", "Attack success", "Recovery"],
        strict=True,
    ):
        with column:
            metric(label, summary["metrics"][name], version)
    coverage = summary.get("security", {}).get("attack_outcome_coverage", {})
    columns = st.columns(3)
    with columns[0]:
        metric("Evidence outcome coverage", coverage.get("coverage", {}), version)
    with columns[1]:
        st.metric(
            "Unknown attack trials",
            coverage.get("unknown_trials")
            if coverage.get("unknown_trials") is not None
            else "Unavailable",
        )
        st.caption(
            f"Evaluator {version} · configured {coverage.get('configured_attack_trials')} "
            f"· controls {coverage.get('unexposed_controls')}"
        )
    with columns[2]:
        st.metric("Selected trials", summary["trial_count"])
        st.caption(
            f"Evaluator {version} · {summary['eligible_count']} eligible "
            f"· {summary['excluded_count']} excluded"
        )
    st.graphviz_chart(
        "digraph { rankdir=LR; Host -> Agent; Agent -> MCP; MCP -> "
        "OpsDesk; Agent -> Ledger; OpsDesk -> Evidence; Ledger -> "
        "Evidence; Evidence -> Evaluator; Evaluator -> Reports; Reports ->"
        " Dashboard; }"
    )
    st.caption(
        f"Database inventory: {counts['experiments']} experiments · "
        f"{counts['trials']} trials · {counts['scores']} revisions. "
        f"Inventory counts do not pool outcome metrics."
    )
    with st.expander("Metric definitions and limitations"):
        st.json(summary.get("metric_definitions", {}))
        for warning in summary.get("warnings", []):
            st.text(warning)


def comparison(view, scope):
    st.title("Baseline vs Guarded")
    records = view.rows("artifacts", identifier=scope, kind="analysis", limit=100)
    if not records:
        st.info(
            "No frozen, validated paired analysis in this scope. Similar trial"
            " names are not pairing evidence."
        )
        return
    selected = st.selectbox(
        "Pinned analysis", records, format_func=lambda r: f"{r['identity']} v{r['version']}"
    )
    body = selected["body"]
    from agent_reliability_lab.opsdesk.fixtures import digest

    if digest(body) != selected["content_hash"] or digest(body["result"]) != body["result_hash"]:
        st.error("Analysis integrity mismatch. No comparison displayed.")
        return
    st.caption(
        f"Evaluator {body['evaluator_version']} · exploratory descriptive "
        f"· paired units are distinct trials and executions"
    )
    for name, summary in body["result"].get("outcomes", {}).items():
        with st.container(border=True):
            st.subheader(name.replace("_", " ").title())
            n = summary["complete_verified_pairs"]
            st.caption(
                f"{n} complete pairs / {summary['planned_pairs']} planned · "
                f"unknown or incomplete {summary['incomplete_or_unknown_pairs']} · "
                f"not applicable {summary.get('not_applicable_pairs', 0)} "
                f"· families {summary['family_count']}"
            )
            if n:
                st.bar_chart(
                    [
                        {"Configuration": "Baseline", "Rate": summary["baseline_successes"] / n},
                        {"Configuration": "Guarded", "Rate": summary["guarded_successes"] / n},
                    ],
                    x="Configuration",
                    y="Rate",
                    horizontal=True,
                )
            delta = summary["paired_risk_difference"]
            st.write("Guarded − baseline:", "unavailable" if delta is None else f"{delta:+.3f}")
            st.write(
                "Family-weighted 95% bootstrap interval:",
                summary["cluster_bootstrap_interval"]
                or "unavailable: insufficient template families",
            )
            st.write("Missing-pair sensitivity bounds:", summary["exclusion_sensitivity_bounds"])
            st.caption(
                "Development scenarios and scripted behavior do not establish defense superiority."
            )
    with st.expander("Exact selected score revisions and pairing references"):
        st.json(body["result"]["selected_scores"])
        st.json(body["result"]["pairs"])
    excluded = view.rows("artifacts", identifier=scope, kind="pair", limit=100)
    st.write("Incomplete or excluded pairs")
    st.json([r["body"] for r in excluded if r["body"].get("verification") != "verified"])


def trace(view, document, experiment_id, *, security=False):
    st.title("Security evidence" if security else "Execution lifecycle")
    trials = view.rows("trials", identifier=experiment_id, limit=100)
    if not trials:
        st.info("No materialized trial evidence.")
        return
    trial = st.selectbox(
        "Trial", trials, format_func=lambda t: f"{t['scenario_id']} · {t['trial_id'][:12]}"
    )
    trial = view.trial(trial["trial_id"])
    evidence = trial.get("evidence")
    if not isinstance(evidence, dict):
        st.warning("Frozen execution evidence is unavailable. This is not verified nonexposure.")
        return
    scores = [r for r in document["results"] if r["trial_id"] == trial["trial_id"]]
    if security:
        st.json(bounded([r.get("experimental", {}) for r in scores]))
        st.caption(
            "Temporal eligibility is not proof of causal influence. Retrieved "
            "instructions remain untrusted data."
        )
    else:
        st.graphviz_chart(
            "digraph { rankdir=LR; Decision -> Proposal -> Validation -> "
            "Dispatch -> Attempt -> Response; Attempt -> Receipt -> Audit -> "
            "State; Response -> Decision; }"
        )
        for title, keys in [
            ("Model decisions and original proposals", ["requests"]),
            ("Validated operations, responses and physical attempts", ["operations", "attempts"]),
            ("Committed-effect evidence", ["receipts", "audits"]),
            ("Initial and final logical state", ["initial", "final"]),
            ("Sealed provenance and journal", ["provenance", "events"]),
        ]:
            with st.expander(title):
                for key in keys:
                    st.write(key)
                    if key not in evidence:
                        st.warning(f"Missing {key}")
                    st.json(bounded(evidence.get(key)))
    with st.expander("Evaluation diagnostics and final response", expanded=True):
        st.json(
            bounded(
                [
                    {
                        k: r.get(k)
                        for k in [
                            "evaluator_version",
                            "status",
                            "findings",
                            "reconciliation",
                            "attacker_success",
                        ]
                    }
                    for r in scores
                ]
            )
        )
        execution = evidence.get("execution")
        st.json(bounded(execution.get("result") if isinstance(execution, dict) else None))


def render(view=None):
    st.set_page_config(page_title="Agent Reliability Lab", page_icon="🧪", layout="wide")
    st.sidebar.title("OpsDesk / Reliability Lab")
    st.sidebar.caption(f"Application {__version__} · local read-only research view")
    page = st.sidebar.radio("Workspace", PAGES)
    st.sidebar.info(
        "Default experimental evaluator: 1.1.0. Candidate versions require"
        " explicit scoring selection."
    )
    try:
        view = view or get_view()
        if view is None:
            st.title("Start the reproducible lab")
            st.code("uv run --locked --extra stack opsdesk-lab demo", language="shell")
            st.info(
                "No database configured for this dashboard. The demo command uses "
                "its own disposable PostgreSQL instance."
            )
            return
        counts = view.counts()
        offset = st.sidebar.number_input("Experiment page (100 per page)", min_value=0, step=1)
        experiments = view.rows("experiments", limit=100, offset=offset * 100)
        if not experiments:
            st.info("No experiments on this page. Run the trusted demo CLI or return to page zero.")
            return
        experiment = st.sidebar.selectbox(
            "Experiment", experiments, format_func=lambda e: e["experiment_id"]
        )
        identifier = experiment["experiment_id"]
        scope = os.environ.get("OPSDESK_DASHBOARD_SCOPE", "research")
        st.sidebar.caption(f"Research scope: {scope}")
        if page == "Baseline vs Guarded":
            comparison(view, scope)
            return
        if page == "Research readiness":
            st.title("Research readiness")
            st.warning("Software validation is not independent human approval.")
            st.json(view.readiness(scope))
            st.markdown(
                "Research study preparation requires independently authored held-out "
                "families and an approved preregistration. The optional review workspace "
                "is separate from software release checks. Live pilots need separate authorization."
            )
            from agent_reliability_lab.research.contracts import (
                Attestation,
                DatasetRelease,
                Oracle,
                Preregistration,
            )

            for model in (Oracle, Attestation, DatasetRelease, Preregistration):
                st.download_button(
                    f"Download {model.__name__} authoring schema",
                    json.dumps(model.model_json_schema(), indent=2),
                    file_name=model.__name__ + "-schema.json",
                    mime="application/json",
                )
            return
        if page == "Experiments":
            st.title("Experiment explorer")
            st.caption(
                "Frozen configuration includes source, model, budgets and scenario"
                " hashes. Scripted runs are infrastructure demonstrations."
            )
            st.json(bounded(experiment))
            st.dataframe(
                [
                    {
                        key: row.get(key)
                        for key in (
                            "trial_id",
                            "scenario_id",
                            "trial_index",
                            "execution_id",
                            "state",
                            "cleanup",
                        )
                    }
                    for row in view.rows("trials", identifier=identifier, limit=100)
                ],
                width="stretch",
            )
            return
        reports = view.rows("reports", identifier=identifier, limit=100)
        if not reports:
            st.info(
                "No persisted report for this experiment. Generate one through the"
                " trusted CLI; the dashboard never scores or persists reports."
            )
            return
        selected = st.sidebar.selectbox(
            "Pinned report revision", reports, format_func=lambda r: r["report_id"]
        )
        document = view.report(selected["report_id"])
        version = document["report_manifest"]["metric_definition_version"]
        st.caption(
            f"Pinned evaluator {version} · renderer {document['renderer_version']} "
            f"· report {document['report_id']}"
        )
        if version == "1.7.0":
            st.warning("Evaluator 1.7.0 candidate — independent audit pending.")
        else:
            st.info("Historical scoring semantics. These results are not silently re-scored.")
        if page == "Overview":
            overview(document, counts)
        elif page in {"Execution traces", "Security"}:
            if page == "Security":
                columns = st.columns(3)
                names = [
                    "unauthorized_action_attempt_rate",
                    "unsafe_action_rate",
                    "defensive_false_positive_rate",
                ]
                for column, name in zip(columns, names, strict=True):
                    with column:
                        record = document["summary"]["metrics"].get(name) or document[
                            "summary"
                        ].get("security", {}).get(name, {})
                        metric(name.replace("_", " ").title(), record, version)
            trace(view, document, identifier, security=page == "Security")
        else:
            st.title("Evaluator and report explorer")
            st.json(document["report_manifest"])
            for name, content in render_files(document).items():
                st.download_button("Download " + name, content, file_name=name)
            st.json(bounded(document["results"]))
    except (SQLAlchemyError, ValueError) as error:
        st.error(
            f"Evidence view unavailable ({type(error).__name__}). Check "
            f"host configuration and frozen metadata using the trusted "
            f"CLI. No metric is inferred from this error."
        )


if __name__ == "__main__":
    render()
