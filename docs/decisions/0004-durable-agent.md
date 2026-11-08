# ADR 0004 — Explicit graph, durable intents and PostgreSQL checkpoints

Status: accepted for Checkpoint 3 (0.4.0). Date: 2026-11-08.

## Context

Checkpoint 2 supplies bound MCP clients and signed host operation IDs. The agent
must survive a lost acknowledgement without inventing another write identity,
and distinguish proposals, attempts and actual effects. Windows MCP subprocess
support must work alongside PostgreSQL checkpoint persistence.

## Decision

Use one custom LangGraph `StateGraph`, existing discovered MCP clients and the
official OpenAI async SDK with live opt-in. A scripted provider indexed by durable
turn exercises the same path offline. No prebuilt agent or extra framework is used.

Use separately Alembic-managed agent metadata/journal/intent tables and official
`PostgresSaver` tables in another schema, JSON-only serialization and
`durability="sync"`. Run its blocking methods in workers: Psycopg async rejects
the Windows Proactor loop, but replacing that loop would break MCP subprocesses.
Preserve the official saver migrations and connection locking.
Run the serialized migration/bootstrap in a worker too, so a concurrent initializer
cannot block the event loop needed by the lock holder. Disable hosted framework
tracing explicitly; model requests remain the sole opted-in AI egress.

Claim executions with session advisory locks. Commit replies and intended
arguments before dispatch. Host proposal/logical write UUIDs derive from execution/
turn/position, never model call IDs. Distinct attempts consume durable budgets;
receipt-backed retries reuse logical IDs. Keep crash outcomes unknown until
evidence exists. Terminal metadata/event commit atomically.

Pin config and sandbox marker/seed on create/resume; hold a shared lifecycle lease
while active. Reset now rotates the existing marker atomically after fixture
verification, preventing paused intents replaying after receipts are cleared.
No business/scenario schema redesign is needed; logical fixtures stay compatible.

## Consequences and alternatives

Execution requires PostgreSQL, even with a fake model; pure unit tests remain
independent. One task uses one execution/thread, with serial attempts. No general
conversation editing/forking API exists. Worker threads do not make SQL instantly
cancellable. Crashes may leave unknown usage/timing/outcomes. Receipt recovery is
specific to OpsDesk, not universal exactly-once execution.

An in-memory saver loses restart safety. JSON-file journals complicate concurrent
claims and atomic events. Framework retries obscure budget boundaries. Raw
provider replies/pickle add disclosure/deserialization risk. Production auth,
retention, scoring, comparative guard policies and attack harnesses are deferred.
