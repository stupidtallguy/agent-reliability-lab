# ADR 0006 — Controlled interception and exposure-bound scoring

Status: accepted for Checkpoint 5 (0.6.0). Date: 2026-11-08.

## Context

Checkpoint 4 separates objective success from agent declarations and reconciles
durable MCP intents/attempts with database receipts/audits. Its two legacy
injection-dependent examples have no exposure runtime. Fault presence and payload
presence alone cannot establish recovery or attack resistance.

## Decision

Add an opt-in trusted runtime plan to the existing graph, with interception before
dispatch, before client output validation and after a validated write response.
Keep actual SDK/server/service calls, schemas and authorization unchanged. Use
logical matching-dispatch ordinals from durable attempts, bounded activation and
versioned hashed sidecars. Append attack text only to allowlisted lower-trust data
fields. Never edit receipts or synthesize business mutations.

Journal trigger/application/observation/model-request links in existing append-only
storage. Verify exact payload presence after size/redaction boundaries before
recording model exposure. Freeze compact evidence plus full trusted harness
configuration outside model context; the agent runtime plan omits scoring goals.
Use existing JSON-capable evaluation tables; no database schema or historical
migration needs changing.

Retain evaluator 1.0.1 behavior for nonexperimental evidence. Experimental evidence
is scored as 1.1.0 with stricter exposure-bound recovery, declared attacker oracles
and explicit unknowns. Re-scoring always appends a revision; old records remain
readable and are never silently replaced. New absent agent fields are omitted
from serialization, preserving previous configuration hashes on resume.

Guarded mode adds provenance framing, fixed trust reminders and explicit host
task-write scopes to the same baseline. Scopes are independent authorization
configuration, not hidden objective predicates. Both modes retain all fundamental
service permissions, receipts and budgets. Paired manifests validate equivalence
and preserve isolated per-repeat state. Scripted observations drive controls,
without an LLM judge or another guardrail model.

## Consequences

The focused development corpus can verify recovery, blocked attempts, role-allowed
workflow hijacks, contamination and false positives without API keys. Negative
findings remain visible. Framing alone does not establish injection resistance.
Scopes require a trusted host to describe intended writes; automatic extraction
from arbitrary requests is deferred. Immediate synthetic timeouts do not measure
real network outage behavior. Crash-window exposure can remain inconclusive even
when receipts safely reconcile the logical write.

Scripted re-execution compares canonical logical boundaries and normalized created
IDs, with explicit divergence. It is not an offline full recording player or
deterministic hosted-model replay. Database owners remain trusted; there is no
production authentication, universal exactly-once guarantee, external exfiltration,
held-out tuning, dashboard or Checkpoint 6 provider comparison.
