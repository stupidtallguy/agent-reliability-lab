# Corrective milestone 0.8.0 validation

Status: local implementation verification complete; evaluator 1.6.0 is a candidate.
No independent approval or live-model result is claimed.

## Protected baseline

- Local and remote main verified at c2b7912456fab61e398d0fdad044bca96602e1e7; clean tree.
- 1.6.0 had no allocated durable scores in the protected database.
- Baseline: **1,029,694 rows, 32 tables**, including all **469** 1.5.0 scores.
- Full per-primary-key hashes and historical scorer bytes saved under ignored
  `.local/remediation16-*` records before edits.
- Protected probe digest: `7b8c7e7a6fa593404480e52415f270cc073735cd014749ecfe408d06e06b4acd`.
- Volume `opsdesk-lab_opsdesk_postgres`, created `2026-11-08T12:06:23Z`, retained.
- Protected database connections use PostgreSQL read-only transactions. No migrations
  or test execution target it; this increment needs no new database migration.

## Isolated verification environment

A separately labeled container `opsdesk-remediation16-tests` uses the same pinned
PostgreSQL 18.6 image, loopback port 55433 and a 1 GiB temporary filesystem mount.
It mounts no persistent volume. The original Compose service, network and port 55432
are unchanged. Databases `opsdesk_lab_test` and `opsdesk_lab_ci` isolate Python 3.11
and 3.12 suites. All integration mutations/migrations/reset/cleanup occur there.
The corrective fixture rejects the protected `opsdesk_lab` database name.

## Verification observations

The existing 427 unit tests passed before the new regressions were added. Early
focused runs exposed diagnostic masking and a legitimate stale interrupted result
on process resume. Those failures were fixed in candidate-only paths. A later
memory probe found a malformed sealed decision shape that raised an attribute
error; typed validation and four regressions were added before the final full runs.
No historical assertion was removed or weakened. Existing unsupported-version
parameters changed from 1.6 to 1.7 because 1.6 is now implemented.

Final local results, 2026-11-10:

| Environment | Unit | Real PostgreSQL integration | Total passed | Failed / errors / skipped |
| --- | ---: | ---: | ---: | --- |
| CPython 3.11.9 | 476 | 378 | 854 | 0 / 0 / 0 |
| CPython 3.12.8 | 476 | 378 | 854 | 0 / 0 / 0 |

There are **94 new tests: 49 unit and 45 integration**. The targeted corrective
suite passed all 94. Final full runs took 744.632 and 822.851 seconds respectively.
JUnit and marker inventories are retained under ignored `.local/remediation16-*`.
Earlier 850-test full runs also passed, before the final four shape regressions.
Counts above describe the final source, not a sum of repeated executions.

Commands used the existing locked uv workflow, with explicit isolated database
URLs. Python 3.12 used the already-installed 3.12.8 environment through
`UV_PROJECT_ENVIRONMENT` and `uv run --locked --python PATH pytest`.
No interpreter was downloaded. Both complete suites include MCP memory/stdio,
agent execution, process restart/lost-response, historical evaluators, pairing,
statistics and export tests.

- `uv run --locked ruff check .`: passed.
- `uv run --locked ruff format --check .`: 203 files already formatted.
- `uv lock --check --offline`: passed, 92 packages; only project version changed
  in the lock. Python 3.11 full planned stack and Python 3.12 core dependencies
  synchronized from the existing lock/cache.
- `uv build --offline`: wheel and source distribution 0.8.0 built successfully.
- Installed the wheel into a separate local virtual environment and imported all
  87 package modules with `-I` outside the checkout; package resolved to that
  environment's `site-packages`, version 0.8.0. Local fresh dependency resolution
  was blocked by package-index timeouts and missing offline cache entries. This
  local check reused installed locked dependency directories; it is **not** proof
  of a fresh dependency installation. CI now performs that fresh installation.
- `docker compose config --quiet`: passed; original Compose/network unchanged.
- Credential/token-pattern and generated-artifact scan passed across 262 candidate
  files. Wheel/source archive contain no local receipts, credentials or traces.
- Original 38 scenarios unchanged; every pre-existing test assertion AST retained.

Hosted CI is an additional delivery gate on the exact pushed commit, with Python
3.11/3.12 PostgreSQL service jobs and fresh wheel dependency installation. Its run
URL and actual job results belong in the delivery report; local execution alone
does not establish hosted CI success.

## CLI and reporting checks

The isolated CLI trial `5a0ca2544d124d0f9d11c4979e5b1bea` belongs to test-owned
experiment `24cd68b31fed41ebb17b7edde926982e`. It used the existing scripted
`attack_body_answer` case, explicit 1.6.0 and memory MCP. Append-only re-scoring
produced versions `[1.6.0, 1.5.0, 1.6.0]`; the original pinned report reproduced
unchanged. Candidate JSON/CSV/Markdown exports were generated, and general/security
ASR records were identical (one scripted exposed success, denominator one).
This is infrastructure validation, not an estimate of real model robustness.

Research CLI registration and read-only `verify-release` passed in isolated scope
`demo_remediation16`: 38 development assignments, zero held-out assignments.

## Final preservation comparison

Every baseline row/primary-key hash, table inventory and score count matched
exactly: **1,029,694 rows / 32 tables / 9,573 scores**. No protected 1.6.0 score
was created. All **469 1.5.0** records, manifests, frozen evidence, report references
and result hashes are covered by this equality check. All eight frozen historical
scorer/projection file byte hashes also matched the pre-edit baseline.

The original 4,224-score/426,287-row snapshot was checked separately: 426,285
original rows remain identical, with only the two metadata revision changes
already permitted during the prior 0.7.0 delivery. This increment made no such
changes. Original 64 evaluator 1.1.0 scores reproduced in memory without persistence;
the 204-score/203-trial/68-experiment/one-report 1.2.0 snapshot matched exactly.
All **206** stored pinned report manifests reproduced from retained results.

The protected probe's full registry/logical/identity/audit/receipt snapshot digest
and original volume identity match the baseline above. Protected schema inventory
still contains only `opsdesk_run_docker_probe_01`.

## Test resource accounting

Container `opsdesk-remediation16-tests` (label `opsdesk.owner=remediation16`) and its
two databases are test-owned. Its temporary filesystem uses no persistent volume.
Normal PostgreSQL checkpoints and smaller WAL retention were configured on this
isolated instance after repeated suites approached its 1 GiB temporary-space limit;
no protected configuration or data was touched.

After local tests/demos, both disposable databases have zero registered sandboxes
and zero physical business run schemas. Persistent test evaluation references
number 1,405 run IDs in `opsdesk_lab_test` and 986 in `opsdesk_lab_ci` (including
focused/repeated runs). Their exact IDs are saved in ignored
`.local/remediation16-test-resources.json`. This inventory does not pretend to
reconstruct an exhaustive event log of already-cleaned standalone fixtures.
The isolated container is intentionally retained for audit; no volume was deleted.
Historical records were not copied into, reset by or cleaned by these tests.

## Remaining gates

Independent read-only audit, genuine oracle reviews/adjudication, independently
authored held-out families and approved confirmatory studies remain outstanding.
All 38 existing scenarios remain development data, and held-out remains empty.
No paid API, dashboard, release tag or public visibility change is part of this work.

Engineering controls for the eight reproduced findings, explicit version routing,
local distribution checks and reproducible test paths are implemented. Independent
candidate approval, real reviewer identity/independence checks, oracle adjudication,
genuine held-out authorship and study approval remain human/research work. The
read-only dashboard and final v1.0 distribution/release validation remain later
engineering tasks. Temporal consistency does not prove causal influence, local
hashes do not authenticate providers, and database administrators remain trusted.
