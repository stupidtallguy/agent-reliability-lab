# Durable execution journal

`opsdesk_agent.events` is append-oriented through `ExecutionStore`. A transactional
per-execution counter assigns contiguous sequence numbers. Run/correlation ID is
the execution UUID. `JournalEvent` exports a strict outer schema. Payloads carry
`schema_version: "1.0"`. This is not a cryptographic tamper-proof log: the database
owner is trusted and can modify tables.

## Records and interpretation

| Event | Meaning / payload |
| --- | --- |
| run_started / run_resumed | Actor reference, sandbox, thread, provider/model |
| model_request | Request UUID, turn, provider/model, input+schema hash |
| model_response | Request UUID, reported model/request ID, usage, call count, bounded answer, duration |
| model_failed | Safe code; no raw SDK exception |
| tool_call_proposed | Host proposal/logical IDs, tool, sanitized arguments/preview, hash |
| tool_call_rejected | Proposal ID, safe code, `effect=not_dispatched` |
| tool_call_started | Proposal/logical IDs, distinct attempt UUID and ordinal |
| tool_call_succeeded / tool_call_failed | IDs, code, duration, bounded result, effect |
| retry_scheduled | Proposal/logical IDs and error code |
| budget_exhausted | Stopping budget |
| run_completed / run_failed / run_interrupted | Response status, reason, completion declaration |

A model decision is a proposal; a started attempt is not proof of a committed
effect. `denied` indicates rejection, `read_completed` confirms a read, and
`receipt_confirmed` confirms the logical write result, including an older receipt.
It does not claim this attempt changed data. `unknown` remains for interrupted/
lost outcomes. Objective success requires business audits, receipts and final
state; [Checkpoint 4 reconciliation/scoring](evaluation-engine.md) now supplies this
independent analysis.

Illustrative shape, not an experiment result:

```json
{
  "execution_id": "EXECUTION_UUID",
  "sequence": 6,
  "event_type": "tool_call_succeeded",
  "timestamp": "2026-11-08T00:00:00Z",
  "elapsed_ms": 125.0,
  "payload": {
    "schema_version": "1.0",
    "correlation_id": "EXECUTION_UUID",
    "tool_call_id": "HOST_PROPOSAL_UUID",
    "logical_operation_id": "HOST_LOGICAL_UUID",
    "attempt_id": "ATTEMPT_UUID",
    "tool": "create_task",
    "effect": "receipt_confirmed",
    "error_code": null
  }
}
```

Exact sanitized arguments/responses live in `operations`; normalized model replies
live in `model_requests`. Checkpoints hold conversation state, not private
chain-of-thought. Intent/attempt events share transactions with their records.
Terminal metadata/event commit atomically after graph persistence. A crash can
leave an unfinished request/attempt; retain uncertainty rather than invent results.

## Timing, usage and capture

UTC records chronology/deadlines. `perf_counter` measures active process segments,
accumulating persisted elapsed milliseconds on resume. Downtime consumes wall
budget but is not active latency. Hard-crash gaps set `timing_complete=false`;
duration can underestimate that unknown interval. Fixture business time is fixed
and independent. The agent journal computes no p95 or objective success metric;
the [evaluation metrics layer](metrics-definitions.md) uses separate observed timing.

Replies record nullable input/output/cached-input/reasoning counts and source
(`provider`, `scripted`, `unavailable`). Missing fields remain null. Aggregates
are null if any physical request lacks that field; request/reported counts show
coverage. Cached/reasoning counts may overlap totals per provider semantics;
never sum them indiscriminately. Prices/costs are not invented. Failed/crashed
requests can have unknown usage. Pricing manifests and cost calculation remain
evaluation work.

Redaction removes known credential environment values, database passwords/DSNs,
recognizable tokens and sensitive structured keys, including JSON-encoded
arguments. Answers/results/messages use the same redactor. Credential-bearing
proposals are rejected. Journal previews are bounded to 2,048 serialized bytes
(larger content becomes a truncated preview); context, observations, proposals
and answers have separate limits. No complete environment, raw signing metadata,
SDK stack or hidden reasoning is captured. This is best-effort redaction, not a
universal secret detector. Only synthetic data belongs in the lab.

Use `opsdesk-agent journal EXECUTION_ID` and `result EXECUTION_ID` to inspect
sanitized PostgreSQL records. No journals are exported to Git. Production access
control, encryption/retention and authenticated HTTP remain deployment work.
Hosted LangSmith tracing is explicitly disabled around graph execution, including
when enabled in the ambient environment; the durable journal remains local.
