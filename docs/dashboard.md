# Agent Reliability Lab dashboard

Launch the complete synthetic demonstration with `uv run --locked --extra stack
opsdesk-lab demo`. It starts a separate temporary database on 127.0.0.1:55435 and
serves Streamlit at [127.0.0.1:8501](http://127.0.0.1:8501). No paid API is contacted.

For an existing authorized research store, set `OPSDESK_DASHBOARD_DATABASE_URL` and
optionally `OPSDESK_DASHBOARD_SCOPE` on the trusted host, then run `opsdesk-lab dashboard`.
Use a SELECT-only PostgreSQL role for stronger deployment isolation. The connection
also enables PostgreSQL read-only transactions and default_transaction_read_only.
The UI has no SQL, database URL, mutation, cleanup, migration or model-execution control.
Downloads serialize existing pinned reports in memory without saving database records.

## Seven workspaces

1. **Overview** shows six reliability KPIs with evaluator, numerator, denominator,
   and evidence status. Open **Cohort filters** to choose an experiment, evaluator,
   or pinned report. Evaluator and report selectors appear when there is a choice.
2. **Baseline vs Guarded** shows rates and denominators from a frozen paired analysis.
   Family intervals and unknown, excluded, and inapplicable pairs are identified.
   Supplementary tool accuracy, latency, cost and coverage use saved reports that
   match the selected score IDs and evaluator. These summaries are descriptive.
3. **Experiments** searches scenario and experiment IDs and filters by configuration.
   Search and sorting apply to the current inventory page of up to 100 experiments.
   Expand a selected record to inspect the frozen configuration and materialized trials.
4. **Execution Traces** follows the journal from model request to tool response.
   The outcome panel distinguishes agent status, objective scoring and receipts/audits.
   Technical evidence stays available in sanitized expandable panels.
5. **Security & Attacks** separates configured payloads, activation, delivery, model
   exposure, operation evidence and evaluated objectives. Select an individual attack
   or fault trial for attribution and recovery details.
6. **Reports & Evaluators** shows evaluator and renderer versions, selected score
   revisions and exact report references. Download the pinned JSON, CSV and Markdown.
7. **Research & Data** shows partitions, scenario families, pair inventory and saved
   preregistrations. The synthetic demonstration has 38 development cases and zero
   held-out cases.

Metrics belong to one selected report or pinned paired analysis. Inventory counts
are separate. Synthetic demonstrations and scripted experiments have explicit purpose
labels. Historical records without a demo marker retain their original purpose. Missing
values appear as unavailable. Text previews are bounded and redacted JSON data.

This is a local developer interface, not production authentication. It must not be
exposed to a LAN/public address. Streamlit telemetry is disabled by the launcher.
AppTest covers all workspaces. PostgreSQL integration tests exercise read-only mutation rejection.

## Design and responsive behavior

`dashboard/design.py` defines the palette and reusable display components.
`dashboard/theme.css` applies the responsive layout and focus styles. The launcher
applies the same light theme to Streamlit's native controls. The system font stack
uses Inter when installed, then Segoe UI or the system sans-serif. Dashboard styling
requires no external fonts, images or JavaScript.

| Tokens | Values |
|---|---|
| Azure and Royal | `#007BFF`, `#1A5FED` |
| Coral and Lavender | `#FF8B6A`, `#B58BE8` |
| White, canvas and border | `#FFFFFF`, `#F0F0F0`, `#D0D0D0` |
| Primary and secondary text | `#111111`, `#475569` |

Overview cards use three columns at desktop widths, two through 1100 px, and one
through 600 px. At 768 px or narrower, the main area has a workspace selector that
works with the sidebar closed. Cohort filters also stay in the main area. Wide
technical tables scroll within their own regions. Chart bars have labels and exact
counts. Open **Exact references** disclosures to select or copy full identifiers
and hashes. Unavailable metrics retain their reason and known denominators.

The dashboard uses Streamlit's native widgets, layout and sanitized HTML APIs.
[Streamlit theming](https://docs.streamlit.io/develop/concepts/configuration/theming) · [Layout API](https://docs.streamlit.io/develop/api-reference/layout/st.columns) · [HTML API](https://docs.streamlit.io/develop/api-reference/text/st.html)

## Reliability evidence

Overview and Reports display evidence-quality measurements for a pinned cohort.
Execution Traces includes a Retry Inspector for logical writes. The
[reliability demo](reliability-demo.md) opens the same read-only dashboard on
frozen revisions of a synthetic external effect.
