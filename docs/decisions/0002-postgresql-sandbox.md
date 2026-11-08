# ADR 0002: PostgreSQL schemas, explicit services and deterministic reset

- Status: Accepted for Checkpoint 1
- Date: 2026-11-08
- Supersedes: ADR 0001's deferral of database infrastructure, not its agent design

## Context

Checkpoint 0 specified three roles, inline `EnvironmentFixture` models and narrow
tool operations. The new scope requests SQLAlchemy/Alembic and internal services,
while explicitly deferring MCP servers. The original roadmap's Checkpoint 1 MCP
deliverable therefore needs revision. Real PostgreSQL behavior must be tested
without tying every unit test to Docker availability.

## Decision

Use maintained SQLAlchemy 2.0 Core with Psycopg 3 and Alembic. Core avoids an
unnecessary ORM object/session layer while retaining safe bound DML, transactional
connections, schema mapping and relational constraints. PostgreSQL 18.6 is pinned
by release and official multi-platform manifest digest in Compose and CI.

Store each run in an explicitly qualified registered schema in a dedicated
OpsDesk database. Validate namespace/database names and require explicit CLI
opt-in. Registry and per-schema ownership markers protect lifecycle operations.
Use restrictive drops; external dependencies must abort cleanup. Version both the
control schema and each run through frozen Alembic revisions. Control/run targets
share a revision stream with explicit schema-specific DDL. In-process Alembic
context use is serialized; independent run services remain concurrent.

Keep legacy fixture/scenario models and all six JSON files unchanged. Wrap them
in `SeedSpec` with typed optional enrichment and persist the exact original seed.
Separate complete canonical logical state from a legacy benchmark projection.
Use fixed seed timestamps, exact Decimal money, stable retry-derived task IDs
and a deterministic simulated mutation clock. Physical identifiers/markers are
excluded from equality. Reset rolls back unless the restored hash matches.

Preserve viewer/support_agent/supervisor roles. Services load roles from stored
actors and intersect role, tenant and scenario permissions. Fail closed for
approval-required calls until a reviewed approval subsystem exists. Keep writes,
idempotency receipts and audit entries atomic; use optimistic task versions and
one run-local write lock. No agent, tool server or experiment runner is introduced.

## Consequences and alternatives

Per-run databases require broader privileges and slower setup. Shared mutable
rows plus tenant filters alone make reset and test leakage harder to reason about.
Schema qualification avoids pooled `search_path` leakage. Schema separation is
not a security boundary against the database owner; service callers are trusted
Python code and future adapters must hide administration entirely.

Serializing same-run writes favors clear retry semantics over throughput; separate
runs can execute concurrently. A fixed simulation clock is reproducible but is
not real operational time. The legacy projection preserves old mutation rules
but does not evaluate newly enriched fields; new benchmark versions must opt in
to those fields deliberately. Keep the three established roles instead of adding
manager/admin aliases without a need. MCP transport contracts, approval grants,
full request traces and network fault behavior require later acceptance gates.

Official implementation references:
[SQLAlchemy transactions/schema mapping](https://docs.sqlalchemy.org/en/20/core/connections.html)
and [Alembic connection sharing/schema tenancy](https://alembic.sqlalchemy.org/en/latest/cookbook.html).
