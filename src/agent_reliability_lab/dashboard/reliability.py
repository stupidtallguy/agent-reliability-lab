"""Presentation of existing evaluation and operational evidence."""

import streamlit as st

from agent_reliability_lab.dashboard.design import exact_refs, fields, short_ref, title_case
from agent_reliability_lab.reliability.inspection import retry_chain
from agent_reliability_lab.reliability.metrics import evidence_quality, render


def quality_rows(records):
    return [
        {
            "Measure": title_case(row["name"]),
            "Rate": "Unavailable" if row["value"] is None else f"{row['value']:.1%}",
            "Numerator": row["numerator"],
            "Denominator": row["denominator"],
            "Scope": row["scope"],
            "Metric version": row["version"],
        }
        for row in records
    ]


def quality(document):
    st.subheader("Evidence quality", anchor=False)
    st.caption("These measures describe pinned score records and their supporting evidence.")
    st.dataframe(quality_rows(evidence_quality(document)), hide_index=True)


def retry_panel(chain):
    st.subheader("Retry Inspector", anchor=False)
    fields(
        [
            ("Tool", chain.get("tool")),
            ("Logical operation", short_ref(chain["logical_operation_id"])),
            ("Commitment", title_case(chain["outcome"])),
            ("Underlying mutation", title_case(chain.get("mutation_evidence"))),
            ("Receipt reuse", chain["receipt_reuse"]),
        ]
    )
    attempts = chain["attempts"]
    if attempts:
        st.dataframe(
            [
                {
                    "Attempt": row["ordinal"],
                    "Status": title_case(row["status"]),
                    "Error": title_case(row["error"]),
                    "Effect": title_case(row["effect"]),
                }
                for row in attempts
            ],
            hide_index=True,
        )
    else:
        st.info("No physical attempt is recorded.")
    st.caption("A physical retry can reuse the logical operation without making a model request.")
    for comparison in chain["context_comparisons"]:
        fields(
            [
                ("Canonical inputs", title_case(comparison["relation"])),
                ("Model boundary", title_case(comparison.get("boundary"))),
                (
                    "Changed fields",
                    ", ".join(map(title_case, comparison["changes"])) or "Unavailable",
                ),
            ]
        )
    exact_refs(
        [
            ("Original proposal", chain["proposal_id"]),
            ("Logical operation", chain["logical_operation_id"]),
            ("Original arguments hash", chain["arguments_hash"]),
            *(
                (f"Model request {number}", value)
                for number, value in enumerate(chain["model_requests"], 1)
            ),
            *((f"Attempt {row['ordinal']}", row["attempt_id"]) for row in attempts),
            *(
                (title_case(name), str(value))
                for name, value in (chain.get("receipt") or {}).items()
            ),
        ],
        label="Exact retry and receipt references",
    )


def retry_inspector(evidence, score):
    operations = [row for row in evidence.get("operations", []) if row.get("operation_id")]
    if not operations:
        return
    operation = st.selectbox(
        "Logical write to inspect",
        operations,
        format_func=lambda row: f"{row['tool']} · {short_ref(row['operation_id'])}",
    )
    retry_panel(retry_chain(evidence, operation["proposal_id"], score.get("reconciliation")))


def demo_workspace(view, execution, page):
    documents = view.reliability_reports(execution)
    if not documents:
        st.info("This execution has no saved synthetic reliability report.")
        return
    st.caption(
        "Scripted infrastructure demonstration · One synthetic notification · "
        "Operational metrics are separate from evaluator scores."
    )
    chosen = st.selectbox(
        "Frozen revision",
        list(reversed(documents)),
        format_func=lambda row: (
            f"Revision {row['revision']} · Delivery {title_case(row['provider']['delivery'])}"
        ),
    )
    fields(
        [
            ("Local intent", title_case(chosen["provider"]["local_intent"])),
            ("Provider", title_case(chosen["provider"]["provider"])),
            ("Delivery", title_case(chosen["provider"]["delivery"])),
            ("Logical operations", chosen.get("logical_operation_count")),
            ("Physical tool attempts", chosen["physical_tool_attempts"]),
            ("Receipts", chosen.get("receipt_count")),
            ("Committed local mutations", chosen.get("local_mutations")),
        ]
    )
    exact_refs(
        [
            ("Reliability report", chosen["report_id"]),
            ("Previous report", chosen.get("previous_report_id")),
            ("Execution", execution),
        ]
    )
    if page == "Execution Traces":
        retry_panel(chosen["retry"])
    elif page == "Security & Attacks":
        st.subheader("Synthetic provider evidence", anchor=False)
        attempts = chosen["provider"]["provider_attempts"]
        st.dataframe(
            [
                {"Attempt": row["sequence"], "Simulated condition": title_case(row["fault"])}
                for row in attempts
            ],
            hide_index=True,
        )
        if chosen["provider"]["unknown_reasons"]:
            st.info("Delivery remains unknown until a terminal provider event is verified.")
    elif page == "Experiments":
        st.subheader("Reliability scenarios", anchor=False)
        st.write([title_case(category) for category in chosen["categories"]])
    elif page in {"Overview", "Reports & Evaluators"}:
        st.subheader("Operational evidence quality", anchor=False)
        st.dataframe(quality_rows(chosen["metrics"]), hide_index=True)
        if page == "Reports & Evaluators":
            for format_name, mime in (
                ("json", "application/json"),
                ("csv", "text/csv"),
                ("md", "text/markdown"),
            ):
                st.download_button(
                    f"Download reliability {format_name.upper()}",
                    render(chosen, format_name).encode(),
                    f"reliability-{chosen['revision']}.{format_name}",
                    mime,
                )
    else:
        st.info("Open Overview, Execution Traces or Reports to inspect this reliability run.")
