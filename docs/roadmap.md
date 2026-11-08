# Checkpoint roadmap

Do not implement a later checkpoint until its scope is explicitly authorized.

| Checkpoint | Deliverables | Acceptance gate |
| --- | --- | --- |
| 0 — Foundation | Architecture, research protocol, threat model, contracts, locked dependencies, scenario schemas/examples, tests and CI | Lock resolves; imports work; valid/invalid schemas tested; lint/tests pass; reviewed documentation; clean private Git commit/push or explicit blocker |
| 1 — Synthetic OpsDesk | PostgreSQL/Alembic, deterministic fixtures, eight internal services, role/resource authorization, fail-closed approval checks, idempotency/audit, Docker/Compose | Real PostgreSQL tests; tenant/role denial; reset equivalence; atomic rollback; duplicate-write prevention; concurrent run isolation; guarded cleanup |
| 2 — Transport and agent (scope to confirm) | Future MCP v2 adapters, then single LangGraph graph, provider/replay adapters, budgets and trace journal | Explicit future scope; transport contract tests; bounded termination; denied writes never commit; replay divergence detection |
| 3 — Evaluator | State/trace/response predicates, tool admissibility oracles, fault/attack harness, versioned manifests | Known-pass/fail controls; metric edge cases; independent oracle review; no LLM-only success decision |
| 4 — Benchmark | Approximately 100 reviewed scenarios and frozen 60/40 split, second provider, preregistration | Template-disjoint held-out store; pilot precision analysis; all scenario release gates pass |
| 5 — Experiments and reporting | Live/replay experiments, Streamlit reports, uncertainty/cost/coverage analysis | Reproducible artifact manifests; paired analysis; missingness and negative findings reported |

## Checkpoint 0 acceptance checklist

1. All required docs and a consistent `src/` package exist.
2. `uv lock --check` and `uv sync --locked --extra stack` resolve on supported Python.
3. Installed package imports from outside the repository working directory.
4. All example JSON specifications validate and round-trip.
5. Invalid fields, references, versions, permission sets and injection settings fail clearly.
6. `uv run --locked pytest` passes.
7. `uv run --locked ruff check .` and `ruff format --check .` pass.
8. Docs consistently describe runtime services/evaluators as planned.
9. Only intentional source/docs/scenarios/lock/config files are staged; secrets and local artifacts stay ignored.
10. Commit on `main`, push without rewriting history, and verify remote SHA and privacy; otherwise report the exact blocker.

See [checkpoint-0-validation.md](checkpoint-0-validation.md) for observed results
and limitations, not benchmark findings.

## Checkpoint 1 status and preparation for Checkpoint 2

Implemented: database/services/state management only, per the revised user scope.
The original Checkpoint 1 MCP-server deliverable was deliberately deferred; see
[ADR 0002](decisions/0002-postgresql-sandbox.md) and
[validation record](checkpoint-1-validation.md). All original scenarios are preserved.

Before Checkpoint 2, run the pinned Compose image on Docker Desktop/Linux and
review hosted CI results. Agree on trusted actor transport, MCP result/cursor/body
contracts and approval grants. Wrap narrow services rather than exposing the
administrative manager. Preserve retry keys and test lost-response reconciliation.
Explicitly authorize the next checkpoint before starting transport or agent work.
