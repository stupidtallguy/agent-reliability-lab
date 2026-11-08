# Checkpoint roadmap

Do not implement a later checkpoint until its scope is explicitly authorized.

| Checkpoint | Deliverables | Acceptance gate |
| --- | --- | --- |
| 0 — Foundation | Architecture, research protocol, threat model, contracts, locked dependencies, scenario schemas/examples, tests and CI | Lock resolves; imports work; valid/invalid schemas tested; lint/tests pass; reviewed documentation; clean private Git commit/push or explicit blocker |
| 1 — Synthetic OpsDesk | Deterministic PostgreSQL fixtures, eight MCP v2 tools, role/resource authorization, approval/idempotency audit, Docker/Compose | Tool contract tests; tenant/role denial tests; repeated reset equality; duplicate write and timeout reconciliation; local isolation verified |
| 2 — Agent | Single LangGraph graph, one provider adapter plus replay adapter, budgets, trace journal, baseline/guarded policies | End-to-end development paths; bounded termination; denied writes never commit; replay divergence detection |
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

## Preparation for Checkpoint 1

Install Docker Engine/Desktop with Compose v2; select and pin a supported
PostgreSQL image digest. Review the v2 MCP APIs for `MCPServer` and `Client` against
the lock. Agree on per-run namespace isolation and the trusted actor transport.
Turn the contracts into concrete request/result models and transaction tests
before writing tool handlers. No model API key is needed for synthetic tool work.
