# ADR 0005 — Independent scoring over frozen evidence

Status: accepted for Checkpoint 4 (0.5.0). Date: 2026-11-08.

## Context

Agent completion is not ground truth. OpsDesk already supplies deterministic state,
registered incarnations, narrow MCP tools, receipts/audits and durable execution
ledgers. The six v1 scenarios contain alternative paths and strict mutation rules,
but lack comprehensive relevance annotations and injection exposure infrastructure.

## Decision

Add a separate evaluation package and `opsdesk_evaluation` schema with its own new
Alembic revision. Preserve committed historical revisions, original scenarios,
fixture hashes and business/tool contracts. Versioned optional oracle sidecars add
requirements and tool rubrics; they cannot weaken existing rules. Hidden scoring
data stays exclusively in evaluator storage, outside prompts/tools/agent state.

Provision a fresh registered schema for every trial. Capture consistent pre/post
states plus compact ledger projections, receipts and audits. Join host logical IDs
through the existing MCP receipt mapping and normalized DTO hashes to audits.
Reconstruct the task audit chain against full snapshots. Missing/conflicting proof
prevents verified success; no journal entry alone proves a committed mutation.
Use interval-valued execution counts when receipt evidence cannot attribute a
commit to a physical retry. Read auditing remains limited to persisted observations.

Store immutable manifests/evidence and append scoring revisions with full oracle,
evaluator version/source hash and exact evidence references. Re-score without
re-executing; aggregate one selected revision per trial. Preserve experiment/
scenario/repeat pairing and expose exclusions, unknowns and small-sample limits.
Use stdlib nearest-rank quantiles and descriptive Wilson intervals, not a new
statistical framework or an LLM judge.

Make three small compatibility changes: share the existing pure MCP receipt-key
mapping, serialize agent/evaluation Alembic contexts with the existing process
lock, and optionally pin cleanup to the expected marker **inside** the cleanup
transaction. This closes a check/cleanup race without changing default existing
callers or database schemas. No agent/MCP workflow redesign is needed.

## Consequences

Only four development cases can execute now; fault/attack cases and held-out runs
are explicitly not executed. Exposure metrics remain unavailable. Scripted plans
are independent fixed infrastructure controls, not LLM research evidence.

Legacy response substring semantics remain limited; new fact groups supplement
them. The legacy state projection stays stable while full-state audit consistency
checks enriched fields. Required operations and partial orders are annotation
contracts; unnecessary allowed calls affect accuracy rather than automatically
invalidating task success.

Runtime call/time budgets use the stricter scenario/host bounds. Legacy cumulative
token and financial ceilings are explicitly post-hoc accounting, not hard runtime
spending guarantees. Live use requires opt-in; missing usage/prices stay unknown.

JSON evidence storage favors explicit reproducibility over premature normalization
of every future trace type. No complete raw journal duplication, production auth,
automatic orphan-run recovery, full recorded-interaction replay, fault injector,
multi-model comparison or dashboard is introduced. Database owners remain trusted;
future retention and access policies must preserve evidence/scoring lineage.
