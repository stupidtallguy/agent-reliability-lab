# Checkpoint roadmap

Current engineering milestone: **0.9.0 / explicit evaluator 1.7.0 candidate**.
The original checkpoint table and handoffs below are historical planning records.
The read-only dashboard, deterministic demo, research workflows and packaging are now
implemented. See checkpoint-9-validation.md for executed checks and
release-readiness-v1.0.0.md for the current remaining gates. Neither a 100-case quota
nor a live pilot is required to manufacture a software release; genuine held-out
validation and research claims need independent human work.

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


## Historical Checkpoint 5 gate

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

## Historical 0.7.0 finalization candidate

The historical checkpoint descriptions above describe their original handoffs.
Checkpoint 6 research infrastructure has now begun: evaluator 1.5.0 candidate,
version-pinned reporting, immutable execution provenance, pending human review,
explicit pairing, split manifests, frozen studies and descriptive statistical controls.
See [finalization validation](finalization-validation.md) for actual checks.

Remaining gates before v1.0, in order:

1. Independent read-only audit of 1.5.0 and research/reporting controls; correct any
   findings under separate version semantics when durable results require it.
2. Actual independent human oracle review, identity/conflict assessment and adjudication;
   independently authored held-out families and approved preregistration. No fake approvals.
3. Separately authorized small live pilot with provider spending controls, if desired;
   report it apart from scripted infrastructure controls.
4. Read-only Streamlit results/trace demonstration on approved scoring semantics.
5. Final Windows/Linux reproduction, distribution, CI, documentation/security review,
   versioned release artifacts and release-validation record. No v1.0 tag in this increment.

## 0.8.0 corrective candidate

The eight reproduced 1.5 audit weaknesses are the scope of evaluator 1.6.0, not a new
agent/research feature expansion. See [validation](checkpoint-8-validation.md).
After verification: independently audit the exact delivered commit; complete genuine
human oracle review and dataset curation; approve studies; then build the read-only
dashboard and finish distribution/release validation. No held-out generalization,
live-model robustness or production readiness follows from scripted tests.


## Checkpoint 9 extension (0.9.0)

Checkpoint 9 adds evaluator 1.7.0 candidate, read-only dashboard, actual scripted product demonstration, research authoring/export workflows, immutable selected-score analyses and safe installation/testing. Application target is 0.9.0; no final tag is created. Remaining software release gate is an independent audit of the exact commit; human research gates remain separately pending in release-readiness-v1.0.0.md.
