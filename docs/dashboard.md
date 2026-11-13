# Read-only research dashboard

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

1. Overview shows the frozen experiment purpose, observed trial splits, evaluator,
   denominators, task/attack/recovery/coverage, unknown counts and separate inventory.
2. Baseline vs Guarded: immutable analysis artifacts with selected score IDs, unique
   paired n, exclusions, unknowns, not-applicable pairs, family intervals and sensitivity.
3. Experiments: frozen configuration, scenario populations, conditions and manifests.
4. Execution traces: original decisions/proposals, validation, dispatches, attempts,
   responses, receipts, audits and initial/final state; unresolved diagnostics remain visible.
5. Security: injection exposures, objective attribution and provenance.
6. Evaluators & reports: exact report/score/renderer identities and JSON/CSV/Markdown downloads.
7. Research readiness shows study prerequisites, held-out inventory, preregistration
   and machine-readable authoring schemas. Oracle Review is optional for the software.

Metrics belong to one selected report or pinned paired analysis. Inventory counts
are separate. Synthetic demonstrations and scripted experiments have explicit purpose
labels. Historical records without a demo marker retain their original purpose. Missing
values appear as unavailable. Text previews are bounded and redacted JSON data.

This is a local developer interface, not production authentication. It must not be
exposed to a LAN/public address. Streamlit telemetry is disabled by the launcher.
AppTest covers all workspaces. PostgreSQL integration tests exercise read-only mutation rejection.
