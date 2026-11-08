# Checkpoint 3 validation record

Date: 2026-11-08. Version: 0.4.0. These are engineering checks, not benchmark
measurements. Checkpoint 4 is not implemented.

## Starting state and environment

Started from clean `main` at `f01d78da6f49d1bb5784d1622e60b4418d78729f`.
Origin: `https://github.com/stupidtallguy/agent-reliability-lab.git`.
GitHub API verification using the existing Git credential manager confirmed private
visibility and default branch `main`; no visibility setting was changed. The app
GitHub connector returned 404 for this private repository, so ordinary Git and
authenticated repository metadata checks were used. No credentials were printed.

Local platform: Windows, CPython 3.11.9, uv 0.13.7, Docker Desktop/Engine 29.9.2,
Compose 5.6.1, actual PostgreSQL 18.6. The existing healthy container and persistent
volume were retained. `internal: false` and loopback-only `55432` were preserved.
No `down -v`, volume deletion or protected sandbox reset was performed.

Installed versions: LangGraph 1.2.20, checkpoint 4.3.1, checkpoint-postgres 3.2.0,
OpenAI 3.46.0 and MCP 2.3.0. Supported Python remains 3.11/3.12; Linux and 3.12
are covered by the updated CI matrix, not claimed as locally executed.

## Observed checks

Commands below use the documented shell database configuration. Local automation
privately loaded matching Compose credentials without rendering them to output.

| Gate | Command / procedure | Actual result |
| --- | --- | --- |
| Pre-change baseline | `uv run --locked pytest` | 195 passed, 24.35 seconds |
| Final full suite | `uv run --locked pytest --tb=short -q` | 264 passed, 70.35 seconds; zero failed/skipped |
| Database-independent selection | `uv run --locked pytest -m 'not integration' --tb=short -q` | 141 passed; 123 deliberately deselected |
| Real PostgreSQL selection | Full suite includes all 123 `integration` tests | Passed; no SQLite replacement or database skip |
| New agent coverage | `tests/agent` (69 tests in final full suite) | 14 pure unit + 55 actual PostgreSQL integration cases passed |
| Dependencies | `uv lock --check`, `uv sync --locked --extra stack`, `uv pip check` | Resolved and compatible |
| Lint / format | `uv run --locked ruff check .`, `uv run --locked ruff format --check .` | Passed |
| Build | `uv build` | Wheel and source archive built |
| Isolated wheel | Clean venv, locked exported dependencies, installed wheel, Python `-I` outside checkout | Imports passed; actual stdio four-tool/five-model-call demo completed with checkpoint |
| Compose | `docker compose config --quiet`, `docker compose ps` | Valid; healthy PostgreSQL; `127.0.0.1:55432` only |
| Migrations | Agent create initializes guarded Alembic schema + official saver; repeated/concurrent initialization tests | Passed; expected metadata/checkpoint tables present |
| Credentials/artifacts | Candidate-file byte scan against known credentials/token patterns; wheel/source member inspection; Git ignore/diff review | Passed; no credentials, local journals, volumes or generated caches included |
| Protected sandbox | Compare logical data, registry/identity, receipts and audit with original snapshot | Unchanged; only `docker_probe_01` remains registered after checks |

All original tests/scenario JSON remain unchanged. Added tests cover discovery and
schema conversion, multi-server/multi-call workflows, malformed/unknown calls,
provider parsing/rate limits/timeouts, real authorization/approval/scenario denial,
tenant/run boundaries, untrusted document framing, durable budgets, redaction,
operation conflicts, retries, process restart and concurrent execution protection.
Hosted framework tracing is explicitly disabled and tested even when ambient
LangSmith tracing is enabled.

The first Windows smoke attempt exposed Psycopg async/Proactor incompatibility;
the official synchronous saver now runs in worker threads and actual stdio tests
pass. An early test expected a word absent from the existing injection fixture;
its assertion was corrected to the actual inert payload. Review also found a
possible async initializer lock deadlock; serialized bootstrap now runs in a
worker and concurrent creation is tested. Final results above include the fixes.

## CLI demonstrations

All seven `uv run --locked opsdesk-agent demo --case CASE` commands were exercised
with unique disposable sandboxes and actual stdio MCP servers, without an API key:

| Case | Status | MCP attempts | Model calls |
| --- | --- | ---: | ---: |
| order | completed | 1 | 2 |
| policy | completed | 2 | 3 |
| customer | completed | 2 | 3 |
| multi_step | completed | 4 | 5 |
| create | completed | 1 | 2 |
| viewer_denied | permission_denied | 1 | 2 |
| error | tool_failed | 1 | 2 |

These demonstrate scripted graph behavior, not measured LLM task success. CLI
`ask --pause-before-tools`, fresh-process `resume`, `result` and `journal` were
also exercised using an explicitly provisioned disposable sandbox: zero tool
attempts before pause, one after resume, and a persisted `run_resumed` event.

Lost-response tests commit a real task then discard the response; a retry reuses
the logical operation ID and returns the receipt with one task. The hard-crash
test uses `os._exit(23)` in a child process immediately after the real MCP write,
before result persistence. A fresh process resumes: two distinct attempts, one
logical operation, one task. The first unknown attempt and incomplete timing are
retained honestly. Completed invocations return cached results; competing claims
are rejected. Reset invalidates paused context by rotating the sandbox marker.

Protected full-state SHA-256 remained:
`7b8c7e7a6fa593404480e52415f270cc073735cd014749ecfe408d06e06b4acd`.

## Delivered changes and limits

Added `agent/{config,state,graph,execution,tool_adapter,persistence,tables,journal,
errors,demo,cli}.py`, model adapters, frozen agent migration, agent tests, execution/
tracing guides and ADR 0004. Updated README, architecture, database/MCP/contracts,
threat/evaluation/roadmap docs, `.env.example`, CI, package version/dependencies and
lockfile. The sole business lifecycle change rotates the existing marker on reset;
business schemas, service rules, tool contracts and scenarios are preserved.

Live OpenAI demonstration: **not run**. No API key was available and no paid call
was authorized by an explicit CLI opt-in. The real adapter was tested offline
through SDK-compatible responses and errors; live model compatibility remains
unverified. No model fallback, prices or benchmark results are fabricated.

One execution/thread serves one task. Calls are serial. No production auth/HTTP,
approval issuance, retention policy, objective evaluator or general fault/attack
harness exists. Redaction is best effort; the host/database owner remains trusted.
Cancellation cannot undo an already committed write. Receipt-backed recovery is
specific to unchanged OpsDesk sandboxes, not universal exactly-once delivery.

Git commit/push and final remote SHA are reported in the delivery response; this
file intentionally cannot contain its own commit hash. Hosted CI status must be
reported separately from these local Windows results.
