# Checkpoint 1 validation record

Date: 2026-11-08. Version: 0.2.0. These are infrastructure checks, not LLM or
benchmark performance results. Checkpoint 2 was not started.

## Starting state and environment

Started from clean `main` at Checkpoint 0 commit
`eaeff5a3df7878c6ec2c8415d9c64dcb7cb09757`. Read the existing docs, schema, all
six scenarios, dependencies and tests before implementation. The original suite
passed **53 tests**. Original scenario JSON, scenario models and tests are unchanged.

Host: Windows, CPython 3.11.9, uv 0.13.7. The installed PostgreSQL 18.3 binaries
were used to initialize a **separate disposable cluster** under ignored `.local/`,
bound only to `127.0.0.1:55439`, with dedicated OpsDesk databases. The existing
Windows PostgreSQL service and its data were not modified. Local-only trust
authentication was used for this disposable cluster; no credentials were read,
requested or printed. Compose/CI target PostgreSQL **18.6**, not the locally
installed patch release. Local testing therefore does not verify 18.6 image behavior.
After validation, the test registry contained zero run sandboxes and the disposable
cluster was stopped cleanly. Its ignored local files were retained; the existing
Windows PostgreSQL service was left running unchanged.

## Actual check results

This host invokes uv at `.bootstrap\Scripts\uv.exe`; commands below use its
normal short name. Database commands used explicit `OPSDESK_DATABASE_URL` and
`OPSDESK_ALLOW_SANDBOX=1` shell settings.

| Check | Command/method | Observed result |
| --- | --- | --- |
| Dependency lock | `uv lock --check` | Passed; 88 resolved packages |
| Full dependency sync | `uv sync --locked --extra stack` | Passed |
| Installed compatibility | `uv pip check` | Passed |
| Original Checkpoint 0 baseline | `uv run --locked pytest` before changes | 53 passed |
| Current unit suite | `uv run --locked pytest -m 'not integration'` | **88 passed**, 36 explicitly deselected |
| PostgreSQL integration suite | `uv run --locked pytest -m integration --tb=short` | **36 passed**, 88 explicitly deselected; no skipped tests |
| Combined coverage | Same unit and integration suites | **124 passing tests total** |
| Lint | `uv run --locked ruff check .` | Passed |
| Formatting | `uv run --locked ruff format --check .` | Passed |
| Distribution | `uv build` | Wheel and source archive built |
| Installed package smoke | Fresh wheel-only environment, working directory outside repository | Import/version and packaged seed/migration resources passed |
| Migration smoke | Wheel-installed `opsdesk provision --run wheel_01 --baseline`, then `migrate` | Passed; control/run Alembic revisions applied and repeat upgrade succeeded |
| Seed/reset CLI smoke | `verify`, `inspect --benchmark`, service create, `reset`, `verify`, `cleanup` | Passed; mutation changed initial-state verification, reset restored it |
| Compose static validation | Official Compose Specification JSON Schema against `compose.yaml` | Passed |
| Docker/Compose runtime | Executable discovery and attempted standalone CLI acquisition | **Blocked**, see below |
| Packaging/hygiene | Wheel/source archive inspection, staged file/credential-pattern review, whitespace and local-link checks | Passed before commit |

Integration coverage includes migrations/GIN index, seeding and integrity, all six
legacy scenario projections, repeated seed equality, reset of state/receipts/audit
and logical clock, foreign keys, cross-tenant relationships, normal/scoped reads,
viewer denial, scenario allowlists, fail-closed approvals, supervisor-only reopen,
atomic writes/audit, identical and conflicting retry keys, stale versions,
concurrent retry/update/provisioning, full-text search and inert injection text,
rollback after a domain write plus receipt, rollback after failed reset reseeding,
duplicate provision refusal, namespace/ownership checks, and cleanup refusal when
an external view depends on sandbox data.

During development, adding migration tracking for the control registry correctly
rejected an earlier unversioned scratch registry with `DuplicateTable`. The final
migration path was then verified from an empty dedicated database. That scratch
bootstrap was never part of a published checkpoint. Initial import/type-annotation
and lint findings were fixed before the passing final suites. No integration
failure was converted to a skip or replaced with SQLite.

## Docker verification boundary

Docker CLI/Desktop/daemon are not installed on the validation host. Attempts to
download the official standalone Compose CLI failed with HTTP 504. Consequently,
`docker compose config --quiet`, image pull, health check, Docker volume behavior,
container-network isolation and actual Compose startup/shutdown **were not run**.
The YAML passed the official [Compose schema](https://github.com/compose-spec/compose-spec/blob/main/schema/compose-spec.json),
which does not verify interpolation, daemon behavior or platform networking.

The release and image digest were checked against official PostgreSQL release
notes and docker-library manifest provenance. CI is configured to use that pinned
18.6 image as a real service, validate Compose with the CLI, and run unit and
integration suites on Linux/Python 3.11 and 3.12. Hosted CI and Python 3.12 results
were not observed locally. Docker runtime verification remains the principal
environment-dependent follow-up; do not describe it as already passing.

## Scope, security limits and Git handoff

Only synthetic data is included. Database files, local configuration, wheel-test
environments, caches, downloaded binaries and generated inspections remain ignored.
No model API, real customer record or production integration was used. Repository
visibility settings were not changed and no publication/deployment was performed.
The final handoff records the committed SHA and remote-head verification.

Isolation applies to cooperating service callers; the database-owner credential
can bypass service policy. There is no RLS, per-agent database login, MCP server,
approval issuance, fault harness, complete attempt trace, benchmark evaluator,
agent, dashboard or experiment runner. Approval-required writes fail closed.
Opaque/snapshot-bound transport cursors and response-size limits are deferred.

Before Checkpoint 2, execute the documented Compose lifecycle on Docker Desktop
or Linux, inspect hosted CI, and agree on actor authentication, approval grants,
MCP transport DTOs/cursors, retry-key preservation and lost-response reconciliation.
