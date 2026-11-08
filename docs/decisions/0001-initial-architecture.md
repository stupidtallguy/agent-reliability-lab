# ADR 0001: Explicit single-agent graph with external authorization

- Status: Accepted for Checkpoint 0
- Date: 2026-11-08

## Context

We need controlled comparisons of tool-using agents, with observable attempts,
committed state changes and reproducible fixtures. A broadly privileged baseline
would conflate unsafe deployment with model behavior. Implementing the full
runtime now would freeze research assumptions before reviewing the protocol.

## Decision

Use a Python 3.11/3.12 `src/` package and Pydantic 2 scenario contracts. Lock all
dependencies with uv, including the optional future stack. LangGraph 1 will own
an explicit single-agent loop. Official MCP SDK 2 will provide tool transport;
do not use v1 `FastMCP` code. FastAPI will expose run control, Psycopg 3 will access
PostgreSQL, and Streamlit will inspect results. Defer runtime services, provider
SDKs and evaluator implementation until their checkpoints.

Enforce server authorization, tenant scoping, idempotency, approvals and budgets
in both baseline and guarded modes. Add bounded guard behavior as a controlled
configuration. Evaluate final domain state, audit/trace events and response
content with declarative predicates and alternative solution paths. LLM judges
are optional secondary annotations. Store six development examples now, and keep
held-out evaluation content separately access-controlled later.

## Alternatives considered

An unrestricted baseline is unsafe and scientifically misleading. A multi-agent
system adds coordination confounders. A monolithic agent framework hides retry
and tool-selection decisions. An ORM, vector store and hosted tracing service
add dependencies before requirements justify them. Pure free-text scenarios
cannot enforce fixture and oracle consistency.

## Consequences

Checkpoint 0 is usable for specification validation, not agent execution. Typed
contracts require versioning and migration as tools evolve. A JSON predicate
schema cannot prove semantic correctness; independent runtime oracle checks remain
required. Locking optional dependencies is more expensive in CI but catches stack
conflicts before implementation. Model nondeterminism remains even with fixed
sampling settings; replay and live results must remain distinct.
