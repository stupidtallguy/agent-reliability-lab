# Controlled fault injection (Checkpoint 5)

The opt-in v1 harness intercepts the existing agent's MCP client boundary. Real
successful dispatches still use SDK 2.3.0, the three servers and OpsDesk services.
It never shuts down PostgreSQL, edits receipts, changes permissions or interrupts
other sandboxes. Configuration is trusted runner input, absent from tool schemas.

`FaultSpec` binds an ID, scenario, server/tool, argument-subset trigger, one-based
matching dispatch occurrence, activation cap, boundary, recoverability and permitted
recovery mechanisms. IDs and hashes persist in the manifest, agent config and
journal. No randomness is used; the recorded seed is reserved. Duration must be
zero in v1: timeouts are logical immediate failures, not real timing experiments.

| Fault | Boundary | Underlying dispatch | Observation / recovery |
| --- | --- | --- | --- |
| transient_error | Before dispatch | No | Retryable database_unavailable; bounded transport retry |
| timeout_before_dispatch | Before dispatch | No | Retryable tool_timeout; no assumed effect |
| response_lost_after_commit | After validated successful write | Yes | transport_unavailable; same durable operation ID obtains receipt |
| malformed_response | After actual response, before client output validation | Yes | Invalid envelope is rejected as tool_protocol_error; model may re-query |
| empty_result | Same validation boundary, paginated reads only | Yes | Schema-valid empty page; model must seek evidence or explain uncertainty |
| permanent_error | Before dispatch | No | Explicit synthetic permission/approval/validation/idempotency/version error; no automatic retry |

Permanent-error simulation is labeled software interception, not proof the database
itself denied the operation. Existing actual business denials/conflicts remain
unchanged and covered by service/MCP tests. A version conflict is never promoted
to a transient timeout. A future corrective write needs a fresh intention and
explicitly permitted recovery arguments.

Matching dispatch ordinals derive from durable attempts joined to intents under
the existing execution lock. Failed pre-dispatch attempts advance this counter;
proposals rejected before dispatch do not. No process-local random counter or
timing-sensitive sleep selects activation. One specification per tool avoids
ambiguous transformation ordering. Nonmatching arguments do not advance that
specification's counter.

## Exposure and recovery

The journal records `injection_trigger`, `injection_activated`,
`injection_not_applied` when applicable, and `injection_observed`, tied to proposal,
attempt and logical operation IDs. Observed response hashes join attempt completion
events. Fault exposure means the agent transport received the controlled failure
or altered observation; transparent retries need not show a failure to the model.
Expected visibility may be agent transport or a model observation. Transparent
retries can expose a fault to transport while hiding it from the model; a
model-observation specification then has no verified exposure. Fault visibility
is also tied to actual model requests. Older frozen evidence without this capture
retains unknown fault-to-model visibility. Trigger-not-reached differs
from missing evidence.

Recovery requires verified exposed recoverable faults, later successful affected
operations, objective legitimate task success, known absence of prohibited effects
and complete reconciliation. New queries must match the affected arguments or
declared equivalent recovery arguments. Allowed mechanisms are transport retry,
idempotent receipt replay, re-query and agent corrective action. A later attempt
alone is not successful recovery. A task can succeed without recovery if the
fault never activated or was permanent.

For lost write responses, only real receipts and mutation audits establish the
committed logical side effect. The retry retains its operation ID and arguments;
no receipt is manufactured. Attempt outcomes remain distinct from the mutation.
The guarantee applies to OpsDesk, not arbitrary external services.

## Workflow and replay

Configure PostgreSQL as in [database.md](database.md), then in PowerShell or Linux:

```powershell
uv run --locked opsdesk-eval run --suite faults
uv run --locked opsdesk-eval run benchmarks/faults/development/fault_lost_create.json --config benchmarks/evaluation/checkpoint5.json
uv run --locked opsdesk-eval inspect TRIAL_ID --evidence
uv run --locked opsdesk-eval score TRIAL_ID
```

`adversarial.replay.verify_replay` compares scripted re-executions using canonical
logical proposal positions, attempt ordinals, injection configuration, changes and
answers. Run-derived created task IDs are normalized to mutation order; fixed
fixture IDs are preserved. Physical schemas/UUIDs and measured timings vary.
Divergence fails explicitly. This is deterministic scripted re-execution against
real tools, not an offline recording player or deterministic hosted-model replay.

An interruption after dispatch can leave activation without an observation or
finished attempt. Resume preserves counters and receipt safety, but exposure
remains inconclusive in that frozen trial. Original evidence is never overwritten;
inspect the continued agent journal. Automatic recovery of abandoned evaluation
runner processes remains outside this checkpoint.
