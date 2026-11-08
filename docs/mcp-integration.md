# OpsDesk MCP integration

Introduced in Checkpoint 2; retained in 0.4.0. Three local stdio servers expose eight
business-service operations using official **MCP Python SDK 2.3.0**. A reusable
trusted client and an isolated demonstration require no LLM or paid API key.
No agent, evaluation engine, attack harness or HTTP listener is implemented.

## Architecture and SDK choice

```text
Trusted host launch configuration (run + actor + tenant + local signing key)
    |
    +-- documents stdio server -> search_documents, get_document
    +-- business stdio server  -> get_order, get_customer, list_customer_orders
    +-- tasks stdio server     -> list_tasks, create_task, update_task
                                  |
                        strict Pydantic adapters
                                  |
                    unchanged OpsDeskService methods
                                  |
                    isolated PostgreSQL run schema
```

Factories return the SDK v2 `Server`, with documented `on_list_tools` and
`on_call_tool` callbacks. This permits one explicit validation/error boundary
without private SDK managers, v1 decorators, deprecated `FastMCP` imports or
provisional middleware. Both input and serialized output are validated by the
adapter; low-level SDK schemas alone do not perform that validation. Services
retain all tenant, scenario, authorization, transaction and state-transition
rules. See [ADR 0003](decisions/0003-bound-stdio-mcp.md).

Reviewed sources and installed APIs on 2026-11-08:
[SDK documentation](https://py.sdk.modelcontextprotocol.io/),
[v2 Server callbacks](https://py.sdk.modelcontextprotocol.io/advanced/low-level-server/),
[in-memory Client testing](https://py.sdk.modelcontextprotocol.io/get-started/testing/),
[structured results](https://py.sdk.modelcontextprotocol.io/servers/structured-output/),
[error behavior](https://py.sdk.modelcontextprotocol.io/servers/handling-errors/) and
[official source](https://github.com/modelcontextprotocol/python-sdk/tree/v2.3.0).
The exact SDK pin is intentional; review these protocol/security adapters before
upgrading it. SDK `Client` negotiates the **2026-07-28** protocol in tested
in-memory and current stdio paths. Legacy compatibility is provided by the SDK
but is not a separately verified support commitment for this checkpoint.

## Database and demonstration

Keep the working development Compose network `internal: false` and the published
port at `127.0.0.1:55432`. The container can make outbound connections. Stricter
evaluation isolation is a future configuration requiring its own connectivity
tests. Do not remove volumes or delete existing developer runs to change networking.
See [database setup](database.md) for password/URL configuration.

PowerShell 7, from the repository root:

```powershell
uv sync --locked --extra stack
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Set a disposable database password in .env if this is a new installation.
docker compose config --quiet
docker compose up -d --wait postgres
$env:OPSDESK_DATABASE_URL = 'postgresql+psycopg://opsdesk_lab:PASSWORD@127.0.0.1:55432/opsdesk_lab'
$env:OPSDESK_ALLOW_SANDBOX = '1'
uv run --locked opsdesk-mcp demo
```

Replace PASSWORD with your URL-encoded local password; do not print the URL.
The Python CLI reads process environment, not `.env`. Linux uses the same uv and
Docker commands with `export NAME=value` for environment variables.

The demo allocates a new `mcp_demo_<random>` run, starts all three stdio servers,
summarizes discoverable schemas, reads an order, creates a permitted task, repeats
the same logical operation, updates the task and demonstrates a viewer denial.
It closes clients, verifies reset and safely cleans up **only its own run**.
Existing/occupied names are refused without cleanup. An optional explicit name
must start with `mcp_demo_`; `docker_probe_01` is never a valid demo target.

```powershell
uv run --locked opsdesk-mcp demo --run mcp_demo_review
```

This is an actual SDK/subprocess/database demonstration, not a prerecorded
simulation. Unexpected failure gives a nonzero exit status. Stdout contains
synthetic results; server diagnostics go to developer stderr.

## Manual launch and trusted client

For a manually managed run, provision a fresh dedicated name and bind a registered
synthetic actor. Generate the local signing key without printing it:

```powershell
uv run --locked opsdesk provision --run mcp_manual_01 --baseline
$env:OPSDESK_MCP_RUN_ID = 'mcp_manual_01'
$env:OPSDESK_MCP_ACTOR_ID = 'support_001'
$env:OPSDESK_MCP_TENANT_ID = 'opsdesk'
$env:OPSDESK_MCP_SIGNING_KEY = uv run --locked python -c "import secrets; print(secrets.token_hex(32))"

# Each command starts and closes its own stdio child with this trusted binding.
uv run --locked opsdesk-mcp list documents --full-schema
uv run --locked opsdesk-mcp list business
uv run --locked opsdesk-mcp list tasks
uv run --locked opsdesk-mcp call business get_order --arguments '{"order_id":"order_001"}'

$operation = uv run --locked python -c "import uuid; print(uuid.uuid4().hex)"
uv run --locked opsdesk-mcp call tasks create_task --arguments '{"customer_id":"customer_001","title":"Manual follow-up"}' --operation-id $operation
# Identical retry: keep the operation ID and arguments unchanged.
uv run --locked opsdesk-mcp call tasks create_task --arguments '{"customer_id":"customer_001","title":"Manual follow-up"}' --operation-id $operation
uv run --locked opsdesk inspect --run mcp_manual_01 --benchmark

# Only after all clients/servers for this run have closed:
uv run --locked opsdesk reset --run mcp_manual_01
uv run --locked opsdesk cleanup --run mcp_manual_01
```

For an MCP-capable local host that owns stdin/stdout, choose the relevant server
command with the same environment. These speak JSON-RPC, not a terminal REPL and
not a network service:

```powershell
uv run --locked opsdesk-mcp serve documents
uv run --locked opsdesk-mcp serve business
uv run --locked opsdesk-mcp serve tasks
```

The reusable Python host abstraction accepts an SDK `Client` in memory, or starts
the installed package as a stdio subprocess via the current Python executable:

```python
import anyio
from agent_reliability_lab.mcp.client import connect_stdio
from agent_reliability_lab.mcp.context import LaunchConfig, LogicalOperation


async def example():
    config = LaunchConfig.from_env()
    operation = LogicalOperation.new()  # Trusted host allocates this once.
    async with connect_stdio("tasks", config) as client:
        schemas = await client.discover()
        arguments = {"customer_id": "customer_001", "title": "Host follow-up"}
        result = await client.write("create_task", arguments, operation)
        retry = await client.write("create_task", arguments, operation)
        assert result.structured_content["data"] == retry.structured_content["data"]


anyio.run(example)
```

The raw client performs no automatic retries. Checkpoint 3's
[execution host](agent-execution.md) persists IDs, correlates proposals and
separately budgets every bounded retry.

## Trusted identity and context boundary

`LaunchConfig` is immutable and validates the run identifier, actor/tenant IDs
and a 32-byte signing key. Startup requires an existing registered sandbox and a
matching database actor/tenant. The role is loaded by existing services; no role
claim is accepted from a request. Missing/invalid launch context fails closed.

No tool schema includes `actor_id`, `tenant_id`, `run_id`, `operation_id`, signing
material or `idempotency_key`. Extra fields are rejected. Ordinary MCP metadata
claims cannot change identity. Every service still intersects role, tenant and
persisted scenario permissions. Discoverability is not permission to execute.
Approval-required operations continue to fail closed. Domain discovery is a fixed
catalog; the agent host filters the model list by scenario availability and its
host allowlist. The backend still rejects forbidden scenario calls.

The bound context records the sandbox ownership marker and seed hash. Every
operation holds a shared lifecycle lock across that verification and the service
transaction. Cleanup/reprovision cannot redirect a running server to a replacement
scenario. Four worker calls per server are admitted concurrently; synchronous
database work runs off the async event loop. Lifecycle administration is never an
MCP tool, resource or prompt. No filesystem, arbitrary SQL or URL-fetch capability
is registered.

The local launch configuration is **not production authentication**. It assumes a
trusted host and local OS account. Someone who controls the process environment,
Python caller or database-owner credential remains outside that boundary. Child
processes receive only required OpsDesk variables plus the SDK's minimal platform
environment; unrelated API credentials are not copied by the trusted client.

## Signed operation identity and retries

Only the trusted host allocates logical write IDs. The client attaches an HMAC
proof under `_meta["opsdesk.lab/operation"]`, binding the configured run, actor,
tenant, tool, logical operation ID and exact JSON arguments. Canonical JSON sorts
keys, uses compact UTF-8 and rejects non-finite numbers. Verification uses constant
time comparison. The model never receives the signing key or a retry-ID argument.

The service key is `mcp_` plus SHA-256 of the canonical identity tuple **excluding
arguments**. Consequently:

- Same logical operation/arguments maps to the same service receipt and original
  task data, including after reconnect or a later task update.
- Once a write is recorded, the same logical operation with different arguments
  maps to the same receipt key, producing `idempotency_conflict`.
- A distinct intentional operation gets a new ID/key, even with an identical title.
- Missing/invalid proofs, changed arguments without a fresh signature, and proofs
  copied from another run/tool/actor fail closed.
- Concurrent retries rely on existing transactional service receipts and the
  run-local write lock; adapters do not duplicate that business logic.

The response-discard test commits a write, discards its result, reconnects and
retries the same operation. It does not simulate every socket/process failure.
There is no claim of universal exactly-once delivery. The Checkpoint 3 host
persists IDs and distinguishes retries from new model proposals.
Changing the signing key requires coordinated client/server launch configuration.
Close clients before reset: it clears receipts. Checkpoint 3 rotates the ownership
marker atomically, invalidating old bound servers/executions. A shared execution
lease blocks reset while the graph is active.

## Inputs, outputs and errors

[Tool contracts](tool-contracts.md) specify all eight tools and captured examples.
Pydantic strict inputs reject unknown fields and scalar coercions. Write schemas
are derived from existing service DTO fields with the retry key removed; patch
validation and supported transitions remain the service contracts. Pagination uses
the existing bounded `after_id` keyset, not a newly invented opaque cursor system.

Every known tool returns the typed envelope in both `structuredContent` and a
matching JSON text block. Document records/matches and envelope provenance label
content `untrusted`; provenance includes source, domain, tool, fixture ID/version
and seed hash. IDs and record versions identify each source record. Document text
is never interpreted, loaded as code, or promoted to policy/permissions.

Tool argument JSON is limited to 16 KiB after SDK decoding. Structured response
payloads are limited to 64 KiB; duplicated compatibility text, SDK metadata and
framing are additional. Oversized results return `response_too_large`, not silently
truncated records. These are application payload bounds, not a complete transport
DoS defense. A committed write whose response cannot be delivered must still be
reconciled with its original operation ID.

Known service failures map to stable allowlisted error codes/messages, including
validation, not-found, permission, approval, version/idempotency conflict and
database-unavailable errors. `isError=true`, `data=null` and error retryability
metadata distinguish them from successes. Unexpected exceptions and output
validation failures become generic `internal_error` with a correlation ID. SQL,
DSNs, exception values, stack traces, environment and paths are never included in
tool results. Detailed unexpected diagnostics go only to developer-side logging;
logs may be sensitive and must never be fed back as model observations.

Unknown tool names return a safe JSON-RPC invalid-params error (`-32602`,
`unknown_tool`), not a fabricated successful tool result. Malformed protocol
messages and SDK transport errors remain SDK-level failures. They are distinct
from an anticipated business error returned by a known tool.

## Tests, HTTP and remaining scope

```powershell
uv run --locked pytest -m 'not integration'
uv run --locked pytest tests/mcp -m 'not integration'
uv run --locked pytest tests/integration
uv run --locked pytest tests/mcp -m integration
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv lock --check
uv build
```

Real integration tests require the Docker PostgreSQL URL above and explicit
sandbox opt-in. Missing connectivity fails, never silently skips. In-memory unit
protocol tests mock only business calls; database/MCP tests use actual PostgreSQL,
SDK dispatch and stdio subprocesses. All original 124 tests remain intact. CI runs
both groups and the isolated demonstration. See [validation](checkpoint-2-validation.md)
for actual session outcomes.

HTTP is intentionally absent. A future authenticated Streamable HTTP deployment
must verify token issuer/audience, principal/tenant/scope and server-assigned run
access before constructing trusted context. It needs TLS, bounded resources,
reviewed OAuth integration, origin protections and isolated logs. Tool arguments
and this local HMAC convention cannot substitute for authentication. Do not expose
these stdio factories through an unauthenticated LAN/public HTTP wrapper.

Checkpoint 3 adds the [durable agent](agent-execution.md), providers and journal
using this transport. The full fault/injection harness belongs to Checkpoint 5.
No scorer, experiment runner or dashboard exists yet.
