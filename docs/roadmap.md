# Checkpoint roadmap

Do not implement a later checkpoint until its scope is explicitly authorized.

| Checkpoint | Deliverables | Acceptance gate |
| --- | --- | --- |
| 0 — Foundation | Architecture, research protocol, threat model, contracts, locked dependencies, scenario schemas/examples, tests and CI | Lock resolves; imports work; valid/invalid schemas tested; lint/tests pass; reviewed documentation; clean private Git commit/push or explicit blocker |
| 1 — Synthetic OpsDesk | PostgreSQL/Alembic, deterministic fixtures, eight internal services, role/resource authorization, fail-closed approval checks, idempotency/audit, Docker/Compose | Real PostgreSQL tests; tenant/role denial; reset equivalence; atomic rollback; duplicate-write prevention; concurrent run isolation; guarded cleanup |
| 2 — MCP tool integration | Three stdio servers/eight tools, strict schemas, trusted actor/run binding, signed host write identity, reusable client/demo | Actual SDK discovery/calls; real PostgreSQL; safe errors; concurrent retries; stdio lifecycle; unchanged legacy scenarios |
| 3 — Agent (implemented) | Custom LangGraph graph, fake/OpenAI adapters, budgets, PostgreSQL checkpoints/intents/journal, CLI | Bounded termination; durable retry/restart; actor binding; actual MCP/PG tests |
| 4 — Evaluation engine (implemented) | Independent state/trace/response oracles, receipt/audit reconciliation, repeated trials, metrics, re-scoring and versioned reports | Real PG/MCP controls; explicit exclusions/unknowns; no LLM-only success decisions; full interaction replay remains future work |
| 5 — Fault and prompt-injection harness (implemented) | Controlled sandbox faults/attacks and recovery/defense evaluation hooks | Isolation; trigger/exposure evidence; denial versus execution checks; no production targets |
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

## Historical Checkpoint 4 gate

Implemented: the existing agent plus independent evaluation, immutable evidence,
append-only scoring, descriptive metrics and exports. All original 264 tests and
six scenario files remain intact. See [ADR 0005](decisions/0005-objective-evaluation.md),
[engine guide](evaluation-engine.md) and [validation](checkpoint-4-validation.md).

Before Checkpoint 5, review versioned fault/attack triggers, exposure provenance,
timeout ambiguity, recovery equivalence rules, fixture isolation and known-pass/fail
attacker objectives. Preserve metrics eligibility and receipt/audit reconciliation.
The two injection-dependent scenarios remain explicitly unexecuted. No full
fault/injection harness, model comparison, dashboard, authenticated HTTP or approval
issuance was added. Review hosted Python 3.11/3.12 CI before expanding scope.


## Checkpoint 5 current gate

Implemented: bounded deterministic fault interception, typed indirect-injection
overlays, verified transport/model exposure, independent attacker/recovery scoring,
explicit host task scopes, benign controls, paired manifests, canonical scripted
re-execution and reports. Original 363 tests, six source scenarios and historical
migrations are preserved. See [ADR 0006](decisions/0006-controlled-injection.md).

Before Checkpoint 6, independently review legitimate tasks, attacker predicates,
scope authoring and template-disjoint splits; freeze corpus/configuration hashes.
Opted-in live pilot measurements must remain separate from scripted validation.
Review false positives, contamination failures, missing exposure and statistical
limits. No second provider, 100-case expansion, dashboard or production auth was
implemented. Checkpoint 6 has not started.
