"""Read-only Streamlit dashboard for frozen OpsDesk evidence."""

import os

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from agent_reliability_lab import __version__
from agent_reliability_lab.dashboard import pages
from agent_reliability_lab.dashboard.design import bounded as bounded
from agent_reliability_lab.dashboard.design import fields, header, styles, timestamp, title_case
from agent_reliability_lab.dashboard.evidence import execution_trace, security
from agent_reliability_lab.research.views import ResearchView, readonly_engine

PAGES = [
    "Overview",
    "Baseline vs Guarded",
    "Experiments",
    "Execution Traces",
    "Security & Attacks",
    "Reports & Evaluators",
    "Research & Data",
]

DESCRIPTIONS = {
    "Overview": "Explore task performance, security outcomes, and evidence from a pinned cohort.",
    "Baseline vs Guarded": "Compare equivalent conditions using pinned scores and verified pairs.",
    "Experiments": "Search experiments and inspect frozen configurations, scenarios, and trials.",
    "Execution Traces": "Follow model decisions, tool calls, responses, and recorded effects.",
    "Security & Attacks": "Inspect injection plans, verified exposure, and committed effects.",
    "Reports & Evaluators": "Inspect scoring revisions and download the exact frozen report.",
    "Research & Data": "Explore dataset partitions, template families, pairs, and study records.",
}


@st.cache_resource
def get_view():
    url = os.environ.get("OPSDESK_DASHBOARD_DATABASE_URL")
    return ResearchView(readonly_engine(url)) if url else None


def report_selection(view, inventory):
    experiment = st.sidebar.selectbox("Experiment", inventory, format_func=pages.experiment_label)
    index = view.report_index(experiment["experiment_id"])
    if not index:
        st.info(
            "This experiment has no saved report. Select another experiment or generate a report "
            "with the evaluation CLI."
        )
        return None
    versions = sorted({r["evaluator"] for r in index if r.get("evaluator")}, reverse=True)
    unknown = any(not r.get("evaluator") for r in index)
    choices = versions + ([None] if unknown else [])
    version = st.sidebar.selectbox(
        "Evaluator version",
        choices,
        format_func=lambda value: (
            "Version unavailable"
            if value is None
            else f"{value} · candidate"
            if value == "1.7.0"
            else value
        ),
        key=f"evaluator_{experiment['experiment_id']}",
    )
    pinned = [r for r in index if r.get("evaluator") == version]
    selected = st.sidebar.selectbox(
        "Pinned report",
        pinned,
        format_func=lambda row: f"{timestamp(row.get('created_at'))} · {row['report_id'][:8]}",
        key=f"report_{experiment['experiment_id']}_{version}",
    )
    if version is None:
        st.info(
            "The saved manifest lacks evaluator metadata. Select a report with a pinned evaluator."
        )
        return None
    document = view.report(selected["report_id"])
    envelope = document["report_manifest"]
    if (
        envelope["metric_definition_version"] != version
        or document["report_id"] != selected["report_id"]
    ):
        raise ValueError("Saved report identity mismatch")
    fields(
        [
            ("Configuration", title_case(experiment.get("configuration"))),
            (
                "Evaluator",
                f"{version} · candidate" if version == "1.7.0" else f"{version} · historical",
            ),
            ("Renderer", document.get("renderer_version")),
            ("Pinned report", document["report_id"][:12]),
        ]
    )
    return document


def render(view=None):
    st.set_page_config(
        page_title="Agent Reliability Lab",
        page_icon=":material/monitoring:",
        layout="wide",
        initial_sidebar_state="auto",
        menu_items={
            "Get help": None,
            "Report a bug": None,
            "About": "Agent Reliability Lab · local read-only analytics",
        },
    )
    styles()
    st.sidebar.html(
        '<div class="lab-brand"><span class="lab-mark" aria-hidden="true"></span>'
        "<div><strong>Agent Reliability Lab</strong>"
        f"<small>v{__version__} · Read-only</small></div></div>"
    )
    page = st.sidebar.radio("Workspace", PAGES, key="lab_workspace")
    st.sidebar.divider()
    scope = os.environ.get("OPSDESK_DASHBOARD_SCOPE", "research")
    header(
        "AI Agent Reliability" if page == "Overview" else page,
        DESCRIPTIONS[page],
        hero=page == "Overview",
    )
    try:
        with st.spinner("Loading frozen evidence…", show_time=False):
            view = view if view is not None else get_view()
            if view is None:
                st.subheader("Connect a research store", anchor=False)
                st.info(
                    "No dashboard database is configured. The synthetic demo starts a "
                    "disposable database."
                )
                st.code("uv run --locked --extra stack opsdesk-lab demo", language="shell")
                return
            if page in {"Baseline vs Guarded", "Research & Data"}:
                st.sidebar.text(f"Research scope\n{scope}")
                if page == "Baseline vs Guarded":
                    pages.comparison(view, scope)
                else:
                    pages.research(view, scope)
                return
            offset = st.sidebar.number_input(
                "Inventory page",
                min_value=1,
                value=1,
                step=1,
                help="Up to 100 experiments per page, newest first.",
            )
            inventory = view.experiment_inventory(limit=100, offset=(offset - 1) * 100)
            if not inventory:
                st.info("This inventory page is empty. Choose page 1 or run the synthetic demo.")
                return
            if page == "Experiments":
                pages.experiments(view, inventory)
                return
            st.sidebar.caption("Default experimental evaluator · 1.1.0")
            document = report_selection(view, inventory)
            if document is None:
                return
            if page == "Overview":
                pages.overview(document, view.counts())
            elif page == "Execution Traces":
                execution_trace(view, document)
            elif page == "Security & Attacks":
                security(view, document)
            else:
                pages.reports(document, view)
    except SQLAlchemyError:
        st.error("The research database is unavailable. Check the host configuration and service.")
    except (ValueError, KeyError, TypeError):
        st.error(
            "The selected evidence could not be displayed. Choose another report or inspect "
            "the frozen record with the CLI."
        )


if __name__ == "__main__":
    render()
