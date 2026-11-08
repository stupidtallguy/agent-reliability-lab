# Checkpoint 2 validation record

Date: 2026-11-08. Project version: 0.3.0. Scope: MCP tool integration only.
No Checkpoint 3 agent, LLM calls, evaluator or attack harness was implemented.

## Starting state and separate networking preflight

Started on `main` at Checkpoint 1 commit
`8b4264978728232bed8a0e3e77560d6bb980bcea`. The only preexisting uncommitted
change was `compose.yaml` changing the development bridge from `internal: true`
to `internal: false`. That change was preserved, documented in database,
architecture and threat-model docs, committed separately and pushed before MCP
implementation:

- Networking commit: `da7c351978a3d560a9285a7963c9378204565922`.
- Remote `main` was verified to match that SHA.
- `docker compose config --quiet` passed.
- Docker container was healthy and published `127.0.0.1:55432`.
- Host-side SQL connected to PostgreSQL **18.6 (Debian 18.6-1.pgdg12+2)**.
- Existing **124 tests passed** against this actual Docker PostgreSQL in this
  session, before MCP implementation. These are reproduced results, not inherited claims.

The bridge permits outbound container networking. No volume was deleted, no
`docker compose down -v` command was run, and no existing sandbox was reset or
removed. The development container remained running throughout validation.

## Validation environment

Windows, CPython **3.11.9**, uv **0.13.7**, Docker client/engine **29.9.2**,
Compose **5.6.1**, and official MCP SDK **2.3.0**. PostgreSQL was the existing
pinned Docker 18.6 image from Compose, not SQLite or the older native cluster.
The SDK client negotiated MCP **2026-07-28** in in-memory protocol checks;
stdio calls used the SDK's current auto-negotiated path. Legacy mode and HTTP
were not separately validated or exposed.

No local password, DSN or signing key was printed. Local validation captured
Compose configuration privately to construct the existing host database URL;
only safe version, health and port information was reported. Helpers, signatures,
wheel environments and synthetic output logs stayed in ignored local directories.

## Actual final results

The host's uv executable was `.bootstrap\Scripts\uv.exe`; commands below use
the normal short name. Database tests used explicit existing shell conventions
for URL and sandbox opt-in, without putting credentials into command output.

| Check | Command/method | Result |
| --- | --- | --- |
| Existing baseline | `uv run --locked pytest` before MCP changes | **124 passed** |
| Full final suite | `uv run --locked pytest --tb=short` | **195 passed in 22.30s**, zero failed/skipped |
| Existing tests preserved | Original scenario/unit/PostgreSQL modules unchanged | 53 scenario + 35 OpsDesk unit + 36 PostgreSQL tests |
| New unit/protocol checks | `tests/mcp/test_protocol_unit.py` in full suite | **39 passed**, actual SDK in-memory boundary, business calls mocked |
| New real integration checks | `tests/mcp/test_postgres_protocol.py` in full suite | **32 passed**, real PostgreSQL and SDK, including stdio subprocesses |
| Ruff lint | `uv run --locked ruff check .` | Passed |
| Ruff formatting | `uv run --locked ruff format --check .` | Passed |
| Lock/dependencies | `uv lock --check`, `uv sync --locked --extra stack`, `uv pip check` | Passed; no unrelated dependency upgrades |
| Package build | `uv build` | Wheel and source distribution built |
| Isolated package | Fresh wheel-only environment, outside source tree | Version/import, packaged migrations/data and full stdio demo passed |
| Compose | `docker compose config --quiet` | Passed against the real local configuration |
| Developer demo | `opsdesk-mcp demo --run mcp_demo_first` and isolated-wheel demo | Eight tools discovered; read/create/update/retry/denial/reset/cleanup passed |
| Tool examples | Eight actual stdio calls on an isolated baseline run | Successful input/data examples captured into tool documentation |
| Repository hygiene | Staged credential-pattern/path review, archive inspection, whitespace/local links | Passed before commit |

The full suite has **127 tests without a database requirement** and **68 integration
tests**. No failed integration was silently skipped. SQLite, fake LLM outputs and
fabricated benchmark results were not used. Early SDK inspection identified v2
metadata as a mapping rather than a Pydantic model; implementation follows the
installed public API. Initial lint findings were corrected before final checks.

## Coverage and error disclosure

Tests verify all eight names/descriptions and strict schemas, typed outputs,
correct/empty/scoped reads, pagination bounds, inert untrusted document metadata,
authorized writes, viewer/scenario denial, fail-closed approvals, optimistic
versions, original-response retries, conflicting reuse, distinct intent,
concurrent retries, response discard/reconnect, independent runs, actor/run
argument rejection, signed proof scope, and rejection of a replacement sandbox
by an existing server instance.

Protocol checks include missing/malformed/extra fields, unsupported write fields,
unknown tools, invalid host context, structured anticipated errors, generic
unexpected errors, malformed service outputs, byte limits, stdio startup/exit,
and absence of diagnostic sentinel values from result text/JSON. A real
non-listening loopback endpoint verifies connection-failure mapping. An explicitly
injected operational failure also tests safe handling. Database programming defects
are treated as internal nonretryable failures rather than retryable outages.

The deliberate response-discard test proves receipt reuse after a committed
write/reconnect. It is not a complete network fault-injection suite or a proof
of exactly-once delivery under every crash/interruption.

## Protected state and remaining limits

`docker_probe_01` was fingerprinted before implementation and compared afterward
using complete logical state, registry, ownership/counter, receipts and mutation
audit. Its SHA-256 fingerprint was unchanged:
`7b8c7e7a6fa593404480e52415f270cc073735cd014749ecfe408d06e06b4acd`.
After test/demo cleanup, it was the only registered run. Its volume and the healthy
existing Docker container were preserved.

The local host/OS account and database administrator are trusted. Launch bindings
and HMAC proofs are not production authentication. No HTTP/OAuth service, durable
agent operation ledger, live-reset coordination, full proposal trace, LLM provider,
fault harness, evaluation engine or dashboard is included. Close servers and
retire logical operations before reset, which deliberately clears receipts.
Opaque snapshot-bound pagination remains deferred in favor of existing keysets.
Developer logs may contain sensitive diagnostics and must not become model input.

Linux/Python 3.12 and hosted CI results were not reproduced locally. CI now runs
unit/in-memory tests, real PostgreSQL/MCP/stdio tests, the isolated demo, Compose
validation and package checks. The final handoff records the implementation commit
and verified remote SHA. Repository visibility was not changed and no publication
or deployment operation was performed.

Before Checkpoint 3, specify durable operation-ID persistence, tool-call correlation,
retry/new-intent handling, budgets and full execution traces. Keep trusted context
outside model messages. Review hosted CI and authorize the next checkpoint
explicitly. The full fault/prompt-injection harness belongs to Checkpoint 5.
