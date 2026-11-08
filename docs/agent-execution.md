# Agent execution (Checkpoint 3)

Implemented: real MCP discovery/calls, one custom graph, optional OpenAI and
scripted providers, durable state, bounded recovery and structured results.
There is no evaluation engine or verified task-success claim.

## Setup and trusted CLI

Follow [database.md](database.md) to set a disposable local password, start
`docker compose up -d --wait postgres`, and set `OPSDESK_DATABASE_URL` plus
`OPSDESK_ALLOW_SANDBOX=1` in PowerShell or Linux. Compose reads `.env`; Python
reads the shell environment. Do not print the fully rendered Compose config/DSN.

```powershell
uv sync --locked
uv run --locked opsdesk-agent demo --case order
uv run --locked opsdesk-agent demo --case policy
uv run --locked opsdesk-agent demo --case customer
uv run --locked opsdesk-agent demo --case multi_step
uv run --locked opsdesk-agent demo --case create
uv run --locked opsdesk-agent demo --case viewer_denied
uv run --locked opsdesk-agent demo --case error
```

Every demo provisions a unique `agent_demo_*` sandbox and starts all three actual
stdio servers. Terminal demos clean only their sandbox; interrupted/uncertain
demos retain it for inspection/resume. Journals/checkpoints remain in separate
agent schemas. `docker_probe_01` and volumes are untouched. Fake plans are fixed
demonstrations, not natural-language understanding; inspect actual observations
using the printed execution ID.

For an explicitly provisioned sandbox (trusted developer identity selection):

```powershell
uv run --locked opsdesk provision --run agent_local_01 --baseline
uv run --locked opsdesk-agent ask "Retrieve order_001 status" --run agent_local_01 --actor support_001 --case order
uv run --locked opsdesk-agent journal EXECUTION_ID
uv run --locked opsdesk-agent result EXECUTION_ID
uv run --locked opsdesk-agent ask "Retrieve order_001 status" --run agent_local_01 --actor support_001 --case order --pause-before-tools
uv run --locked opsdesk-agent resume EXECUTION_ID
# Only after executions are finished or deliberately retired:
uv run --locked opsdesk cleanup --run agent_local_01
```

Replace `EXECUTION_ID` with the printed ID. Commands also work on Linux. Resume
loads persisted configuration and offers no identity override; the Python API
requires a matching hash. Invalid/missing actors fail closed at creation. The
demo uses support, except `viewer_denied`. Local launch is not authentication.

## Optional real model

Set `OPENAI_API_KEY` privately in the shell. Choose an exact tool-capable model
available to the account; no model ID or price is assumed:

```powershell
uv run --locked opsdesk-agent ask "Read order_001 and its customer's orders; summarize the status." --run agent_local_01 --actor support_001 --provider openai --model YOUR_MODEL_ID --live
uv run --locked opsdesk-agent resume EXECUTION_ID --live
```

Both model ID and `--live` are required before CLI creation of a live execution.
No live requests run in CI. Unavailable models fail without fallback. The SDK
uses the official HTTPS endpoint, `store=False`, no automatic retries and no
temperature determinism claim. Unsupported model options cause a safe provider
failure; check compatibility before experiments. Hidden reasoning is not captured.
No live model was exercised in this checkpoint's local validation.

## Durable operation lifecycle

Each execution has a UUID, distinct thread UUID, immutable sandbox/actor/tenant/
config association, pinned marker/seed, UTC deadline and checkpoint reference.
Fresh MCP signing keys are generated on connection, never persisted. The model
receives the task, fixed policy, discovered schemas and lower-trust observations,
with no identity-selection arguments. Assigned actor references returned as
business data confer no authority.

1. Persist the normalized model reply before validating proposals.
2. Assign a host proposal UUID from execution/turn/position. Model call IDs only
   correlate messages; they do not authorize operations.
3. For writes, assign a distinct logical UUID derived from that proposal.
4. Commit exact sanitized intended arguments and SHA-256 before dispatch.
   Sensitive arguments are rejected, not silently changed and executed.
5. Reserve a fresh attempt UUID and durable budget, then call existing MCP.
6. Commit response/outcome before adding it to graph conversation state.
7. On replay, use cached results. Unknown writes reuse the logical UUID and
   service receipt. Changed arguments under the same intent fail safely.

Different proposals are different intentions even with identical arguments.
Repeated intentional creates produce separate tasks; the host cannot infer
semantic duplicate intent from titles. Framework node retries are disabled;
application retries are explicit and separately journaled.

The restart test exits a separate process after a real write returns but before
recording its response. A fresh process resumes and obtains the original receipt:
one task, two attempts. This guarantee is scoped to OpsDesk receipts in an
unchanged sandbox, not arbitrary external services. Hard crashes may leave an
old attempt `started` with unknown outcome after a later receipt confirms the write.

## Budgets and recovery

| Limit | Default |
| --- | ---: |
| Model requests | 8 |
| MCP attempts, including retries | 16 |
| Active graph nodes | 64 |
| Extra attempts per logical call | 1 |
| Wall duration, including downtime | 120 seconds |
| Model / tool timeout | 30 / 20 seconds |
| Requested model output tokens | 1,024 |
| Serialized context including schemas | 65,536 bytes |
| Tool observation | 16,384 bytes |
| Final answer | 8,000 characters |

`Budgets` validates host overrides. Counters persist before calls; startup and
discovery are inside the wall deadline. Each active node checks graph/wall limits.
In-flight SQL/remote writes may outlive cancellation briefly. Existing statement/
lock timeouts still apply; no further dispatch follows exhaustion.

Only explicitly retryable errors retry. Permission, approval, validation,
version/idempotency conflicts, not-found and oversized results never auto-retry.
Disconnects/tool timeouts may retry within limits, preserving write identity.
Model errors terminate with safe reasons; no blanket model retry is implemented.
The model can explain permanent errors or propose another action within budget.
A recorded permanent tool error keeps final status conservative even if a fluent
response follows.

## Status and resume

`completed` means a final response exists, not verified success. Separate fields
describe response completion and nullable model-declared completion.
`permission_denied`, `tool_failed`, `budget_exhausted` and `failed` are terminal
and cached. `interrupted` is resumable. A hard crash leaves `running`; a new lock
holder may resume it. Restart preserves counters/deadlines. Exceptions recorded
as `failed` are not silently resumed. Database loss can prevent saving a terminal
result; inspect the durable row/checkpoint after recovery and reuse the same ID.

Session advisory locking permits one active process per execution. Completed
invocations return their recorded result without another model/tool call. A
shared sandbox lease blocks reset/cleanup while active. Reset rotates the marker
and clears receipts; old executions/servers fail closed even though logical data
matches. Metadata remains inspectable after sandbox cleanup. Automatic retention
deletion is not yet implemented.
