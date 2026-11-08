# OpsDesk PostgreSQL sandbox

Implemented in Checkpoint 1: PostgreSQL infrastructure, migrations, deterministic
fixtures, isolated state lifecycle and eight internal Python services. Checkpoint 2
adds [stdio MCP adapters](mcp-integration.md); Checkpoint 3 adds the
[durable agent](agent-execution.md) around unchanged service contracts. No
evaluator, experiment runner or dashboard is implemented.

## Prerequisites and configuration

Use Python 3.11/3.12, uv 0.13.7, and Docker Desktop with Linux containers on Windows,
or Docker Engine with the Compose plugin on Linux. Compose uses the official
`postgres:18.6-bookworm` image, pinned to a multi-platform manifest digest. Version
18 remains supported through 2030; 18.6 is the current supported minor checked on
2026-11-08. Sources: [PostgreSQL version policy](https://www.postgresql.org/support/versioning/),
[18.6 release notes](https://www.postgresql.org/docs/release/18.6/),
[official image](https://hub.docker.com/_/postgres), and
[manifest provenance](https://github.com/docker-library/repo-info/blob/master/repos/postgres/remote/18.6-bookworm.md).
Update version and digest together after review; do not use `latest`.

PowerShell, from the repository root:

```powershell
uv sync --locked --extra stack
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env: set POSTGRES_PASSWORD to a disposable local password.
docker compose config --quiet
docker compose up -d --wait postgres

# The Python CLI reads shell variables, not .env. Replace PASSWORD with the
# URL-encoded password you placed in .env; do not paste real credentials into logs.
$env:OPSDESK_DATABASE_URL = 'postgresql+psycopg://opsdesk_lab:PASSWORD@127.0.0.1:55432/opsdesk_lab'
$env:OPSDESK_ALLOW_SANDBOX = '1'
uv run --locked opsdesk provision --run demo_01 --baseline
uv run --locked opsdesk migrate --run demo_01
uv run --locked opsdesk verify --run demo_01
uv run --locked opsdesk inspect --run demo_01
uv run --locked opsdesk reset --run demo_01
uv run --locked opsdesk cleanup --run demo_01
docker compose down
```

Provision creates the run schema, applies migrations and seeds it in one
transaction. `migrate` is an idempotent explicit upgrade command for an existing
registered run; it is not necessary before initial provision. No manual SQL or
separate `alembic.ini` is required. Use the guarded CLI instead of invoking an
unscoped Alembic command. The control registry also has its own Alembic version.

On Linux the Docker commands are the same. Use `cp .env.example .env` and:

```sh
export OPSDESK_DATABASE_URL='postgresql+psycopg://opsdesk_lab:PASSWORD@127.0.0.1:55432/opsdesk_lab'
export OPSDESK_ALLOW_SANDBOX=1
uv run --locked opsdesk provision --run demo_01 --baseline
```

An existing disposable PostgreSQL 18 installation can also be used with the same
URL/configuration and CLI; Docker is not required by Python. Create only a new,
dedicated database and role. Approved database names are exactly `opsdesk_lab`,
`opsdesk_lab_test`, and `opsdesk_lab_ci`; SQLite and generic/production database
names are refused. Never aim these commands at a production database, even if
renamed. Database naming/opt-in checks are accident prevention, not authentication.

Compose publishes only `127.0.0.1:55432` by default, uses a development bridge
network with `internal: false` and a health check, and stores PostgreSQL 18 data in a Docker-managed named volume
mounted at `/var/lib/postgresql`. `docker compose down` preserves that volume.
Do not delete the volume as part of per-run reset. `.env`, `.local/`, `pgdata/`,
environments and build artifacts are ignored. The Compose database owner is a
local administrative credential, never an agent credential. CI uses trust auth
only for its disposable runner-local PostgreSQL service; local Compose requires
a password and SCRAM host authentication.

On the verified Windows Docker Engine configuration, `internal: true` prevented
the database port from being published to the host. Local development therefore
preserves `internal: false`: the container can make outbound network connections,
while inbound PostgreSQL access remains bound to loopback. This is not an egress
isolation boundary. Later security-evaluation environments may use stricter
network isolation with an explicitly tested host-access path. Never remove the
data volume to diagnose networking, and preserve existing developer sandboxes
such as `docker_probe_01`.

## Tables and relationships

```mermaid
erDiagram
    TENANTS ||--o{ ACTORS : scopes
    TENANTS ||--o{ CUSTOMERS : scopes
    TENANTS ||--o{ DOCUMENTS : scopes
    CUSTOMERS ||--o{ ORDERS : places
    CUSTOMERS ||--o{ ACCOUNTS : owns
    CUSTOMERS ||--o{ TASKS : concerns
    ORDERS ||--o{ PAYMENTS : receives
    ORDERS o|--o{ TASKS : references
    ACTORS o|--o{ TASKS : assigned
    ACTORS ||--o{ WRITE_RECEIPTS : retries
    ACTORS ||--o{ MUTATION_AUDIT : performs
    TASKS ||--o{ MUTATION_AUDIT : records
```

| Table | Purpose and constraints |
| --- | --- |
| tenants | Explicit tenant IDs for scoped foreign keys |
| actors | Fixed synthetic identity and `viewer`, `support_agent`, `supervisor` role |
| customers | Name, unique tenant/email, fixed creation time, positive version |
| accounts | Customer account status, normalized separately from customer identity |
| orders | Customer, status, `NUMERIC(12,2)` amount, three-letter currency, UTC timestamps, version |
| payments | Related order, exact amount, status, nullable settlement time |
| tasks | Customer, optional order/assignee, title/description, status/priority, UTC timestamps, optimistic version |
| documents | Title/content/category/version, publication time, always `untrusted`; generated English `tsvector` and GIN index |
| sandbox_identity | Singleton run ID, ownership marker and deterministic mutation counter |
| write_receipts | Unique `(tenant, actor, operation, idempotency_key)`, canonical argument hash and original response |
| mutation_audit | Committed write sequence, actor, operation, task and before/after payloads |
| alembic_version | Revision in each run schema and the control schema |
| opsdesk_control.sandboxes | Run/schema ownership, immutable original seed/policy, seed and initial logical-state hashes |

Record IDs are unique within a run and are reused across runs. Composite tenant
foreign keys prevent cross-tenant relationships. A task's optional order must
belong to its customer, not merely exist. Status/priority/role, positive-version,
nonnegative-money, currency and nonblank-task-title constraints also apply at the
database boundary. Common customer/status lookup paths have indexes. Full-text
search uses `plainto_tsquery` and bound input, returns results in stable document-ID
order, and never interprets document text as instructions. Search is lexical,
not semantic/vector retrieval.

SQLAlchemy 2.0 Core generates parameterized DML and schema-qualified queries;
Psycopg 3 is the driver. Schema identifiers are validated separately and emitted
through SQLAlchemy DDL constructs. No `search_path` switching or agent SQL API
exists. Alembic revision `0001_opsdesk` contains frozen table definitions and
handles the control/run schema targets explicitly; it never imports mutable
application table metadata. Future revisions must be additive migrations rather
than edits to that revision. See [ADR 0002](decisions/0002-postgresql-sandbox.md).

## Fixtures, business assumptions and scenario compatibility

The six Checkpoint 0 JSON files and `EnvironmentFixture` contract are unchanged.
`from_scenario` wraps the exact inline fixture and actor in `SeedSpec`. Scenario
available/permitted/approval lists are persisted with the run and enforced by
services. Injections are parsed as part of scenarios but are **not applied**;
the attack/fault harness belongs to a later checkpoint.

`SeedSpec` v1 wraps `environment`, `actors` and optional typed maps of customer,
order, task and document details keyed by existing IDs. The richer bundled
`opsdesk/data/baseline.json` supplies:

- Two tenants, four actors, five customers, six orders, five payments, four accounts,
  four tasks and four documents.
- A recently shipped, settled order eligible for refund **review**, an old order
  outside policy, pending/failed payments, a cancelled order and a suspended account.
- Two orders for one customer to make "my order" ambiguous; resolved, open and
  in-progress tasks; a supervisor-only reopen operation; a cross-tenant record.
- An inert prompt-injection training memo. Reading it causes no action.

Policy evaluation date is fixed at **2026-02-01**; refund review requires an active
account, settled payment, paid/shipped order and creation on/after 2026-01-02.
These are synthetic business facts for future evaluations, not an implemented
refund engine or permission to issue money. No refund operation exists.

Missing enrichment receives documented deterministic defaults: synthetic `.invalid`
email; customer creation 2025-01-01 UTC; record/publication time 2026-01-15 12:00 UTC;
USD total equal to the sum of fixture payment cents; task normal priority and no
assignee/order; document category policy/version 1. Explicit order dates precede
the simulation mutation epoch. Task creation and settled payment dates are at
least their related order's creation date. Pending/failed payments have no
settlement timestamp. All fixtures use fixed data; no uncontrolled random data
generation or wall-clock-dependent business state exists.

```powershell
uv run --locked opsdesk provision --run scenario_01 --scenario benchmarks/development/multi_step_resolve_task.json
uv run --locked opsdesk inspect --run scenario_01 --benchmark
uv run --locked opsdesk verify --run scenario_01
uv run --locked opsdesk reset --run scenario_01
uv run --locked opsdesk cleanup --run scenario_01
```

Full `inspect` produces canonical logical state including typed enrichment and
actors. Decimal money is serialized as exact two-place strings and UTC times as
ISO strings. `--benchmark` emits the original six collections keyed by record ID,
including integer payment cents, and excludes infrastructure/version/timestamp
enrichment absent from v1. Thus task resolution changes only `status` and `version`
in that projection, preserving the existing allowed-change rules. This projection
must be versioned before future scenarios assess enriched fields; no evaluator
or result-scoring implementation is included here.

## Isolation, reset and cleanup

Run IDs match `[a-z][a-z0-9_]{1,31}` and map to `opsdesk_run_<id>`. Provision refuses
existing registrations or occupied schema names. The control registry and a
matching random ownership marker inside the schema must agree before every
operation. Marker randomness identifies physical resources; it is excluded from
logical state and is not a secret or an authorization credential.

Every service transaction takes a shared PostgreSQL advisory run lock. Snapshot,
reset, migration and cleanup take the exclusive counterpart, so a reset cannot
race an in-flight service operation. Writes additionally lock the run's mutation
counter row; this serializes writes inside one sandbox, while separate runs remain
independent. Alembic calls are serialized in-process because its context proxy is
global; PostgreSQL control/run locks also protect separate processes.

Reset validates the stored seed hash, deletes only known run tables in dependency
order, reloads the saved original, clears receipts/audit, resets the logical clock,
and compares the restored state hash before commit. Any error rolls back the
whole reset. It never loads a caller-supplied replacement fixture. Reusing the
same sequence of writes after reset yields equal IDs, responses and timestamps.

Cleanup requires registration and a matching marker. It drops only known tables
and the named schema using **RESTRICT**, never CASCADE or database deletion.
Unknown objects or external dependent views cause rollback and require developer
inspection. Tests verify that a public-schema dependent view survives a rejected
cleanup. Database files, OIDs, schema names, markers and storage layout are not
part of reproducibility; canonical logical data is.

## Authorization, transactions and idempotency

`ActorContext` contains only a trusted `actor_id` and `tenant_id`. Services load the
role from PostgreSQL, intersect it with scenario policy and check every referenced
resource's tenant. Missing and cross-tenant records produce identical `not_found`
errors. Unknown actors/tools/roles default to deny. Context is host-supplied, not
an authentication mechanism; never let an agent select an arbitrary actor ID.

| Role | Own-tenant reads | Task create/update | Reopen resolved tasks |
| --- | --- | --- | --- |
| viewer | Yes | Denied | Denied |
| support_agent | Yes | Yes, forward transitions | Denied |
| supervisor | Yes | Yes | Yes |

Manager/administrator role suggestions were not added: retaining the existing
supervisor contract avoids unnecessary schema changes. Assignment, deletes,
refunds, account writes and arbitrary database operations are not exposed.
Approval-required operations fail closed with `approval_required`; granting,
expiry and verification of approvals are deferred, not bypassed with a boolean.

Task creates and updates commit their domain change, mutation counter, receipt
and before/after audit together. Failed constraints, permissions, stale versions
or unexpected exceptions roll back everything. `ServiceError.detail` contains a
safe code/message/retryability flag; raw database diagnostics stay outside future
tool responses. Invalid Pydantic inputs fail before service execution.

Idempotency scope is `(run, tenant, actor, operation, key)`; canonical argument
hashes exclude the key. Same key/arguments returns the exact original response,
even if the task subsequently changed. Same key/different arguments fails with
`idempotency_conflict`. Different keys describe distinct intentional operations;
there is no fuzzy title-based deduplication. Authorization is checked again before
receipt replay. Update requires the observed version and increments it atomically;
stale concurrent proposals get `version_conflict`.

MCP adapters retain one host-assigned key per logical write across
transport retries. A fresh retry key can create a second task. Receipts allow
reconciliation after a lost response; Checkpoint 3 adds durable bounded retries.
Successful writes advance a fixed simulation clock from
2026-02-01 UTC by one second. This clock is for deterministic state, not latency
measurement. Audit entries cover committed changes, not denied attempts; the
agent journal records proposals/attempts separately; audits remain evidence of
committed changes. See [agent tracing](agent-tracing.md).

## Tests and limitations

```powershell
uv run --locked pytest -m 'not integration'
# Requires the real PostgreSQL URL and opt-in above; missing/unreachable DB fails.
uv run --locked pytest -m integration
# Full suite with configured PostgreSQL:
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

Integration tests use real PostgreSQL, never SQLite, and do not skip missing or
failed database connections. Test run IDs are unique; logical fixtures are equal.
CI runs unit/integration checks against the pinned PostgreSQL image on Python
3.11/3.12 and validates Compose configuration without printing credentials.

Schema isolation and service authorization protect cooperating callers, not a
malicious process holding the database-owner connection. There is no PostgreSQL
row-level security or per-agent login. Read pagination uses explicit bounded
`after_id` keysets, not snapshot-bound opaque MCP cursors. Full-text search uses
English stemming and stable ID order rather than relevance ranking. Approval
issuance, transport-level body-size controls and fault injection remain deferred.
Checkpoint 3 adds bounded observations and request/denial traces. This is local
synthetic infrastructure, not a hardened hosted
multi-tenant product. See the actual [Checkpoint 1 validation record](checkpoint-1-validation.md).

Checkpoint 3 adds separate `opsdesk_agent` metadata and `opsdesk_agent_checkpoints`
schemas without changing business tables. Reset atomically rotates the existing
registry/identity marker after fixture verification, invalidating old clients and
paused executions whose receipts were cleared. Logical data remains equivalent;
physical incarnation deliberately changes. Active agents hold shared leases, so
reset/cleanup wait or fail at the configured lock timeout. See [ADR 0004](decisions/0004-durable-agent.md).
