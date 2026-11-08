# Checkpoint roadmap

Do not implement a later checkpoint until its scope is explicitly authorized.

| Checkpoint | Deliverables | Acceptance gate |
| --- | --- | --- |
| 0 — Foundation | Architecture, research protocol, threat model, contracts, locked dependencies, scenario schemas/examples, tests and CI | Lock resolves; imports work; valid/invalid schemas tested; lint/tests pass; reviewed documentation; clean private Git commit/push or explicit blocker |
| 1 — Synthetic OpsDesk | PostgreSQL/Alembic, deterministic fixtures, eight internal services, role/resource authorization, fail-closed approval checks, idempotency/audit, Docker/Compose | Real PostgreSQL tests; tenant/role denial; reset equivalence; atomic rollback; duplicate-write prevention; concurrent run isolation; guarded cleanup |
| 2 — MCP tool integration | Three stdio servers/eight tools, strict schemas, trusted actor/run binding, signed host write identity, reusable client/demo | Actual SDK discovery/calls; real PostgreSQL; safe errors; concurrent retries; stdio lifecycle; unchanged legacy scenarios |
| 3 — Agent (implemented) | Custom LangGraph graph, fake/OpenAI adapters, budgets, PostgreSQL checkpoints/intents/journal, CLI | Bounded termination; durable retry/restart; actor binding; actual MCP/PG tests |
| 4 — Evaluation engine | State/trace/response predicates, metrics, replay, versioned manifests | Known-pass/fail controls; edge cases; oracle review; no LLM-only success decisions |
| 5 — Fault and prompt-injection harness | Controlled sandbox faults/attacks and recovery/defense evaluation hooks | Isolation; trigger/exposure evidence; denial versus execution checks; no production targets |
| 6 — Benchmark | Approximately 100 reviewed scenarios and frozen 60/40 split, second provider, preregistration | Template-disjoint held-out store; pilot precision analysis; scenario release gates |
| 7 — Experiments and reporting | Live/replay experiments, Streamlit reports, uncertainty/cost/coverage analysis | Reproducible manifests; paired analysis; missingness and negative findings reported |

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

## Checkpoint 3 status and preparation for Checkpoint 4

Implemented: existing sandbox/MCP plus one durable agent. Original scenarios and
195 Checkpoint 0–2 tests remain intact. See [ADR 0004](decisions/0004-durable-agent.md),
[execution](agent-execution.md) and [validation](checkpoint-3-validation.md).

Before Checkpoint 4, review journal/receipt/state reconciliation, metric denominators
and missingness, known-pass/fail controls and multiple valid solution paths. Freeze
evaluator versions and distinguish model completion from objective success. Review
hosted Linux/Python 3.12 CI results. No evaluator, full attack/fault harness,
authenticated HTTP or approval issuance is implemented in Checkpoint 3.
