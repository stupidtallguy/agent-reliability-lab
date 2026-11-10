# Checkpoint 9 validation record

This records internal engineering validation, not an independent audit. Application
0.9.0 / explicit evaluator 1.7.0 / renderer 2.2.0; default experimental selector 1.1.0.
Starting local and remote main: 3255e152b3a56d4f62fa6fb552fa815cbcd7a37d, private,
clean index/worktree. No existing work was discarded. No paid/live model call occurred.

## Scope and implementation

AUD16-01..06 are addressed in candidate modules; see audit-remediation-1.6.md.
Additional boundary checks cover malformed raw captures, experiment envelopes and
trial cleanup metadata, duplicate materialized population aliases, malformed objective
references and present-but-invalid comparison hashes. Seven dashboard workspaces,
actual scripted agent/MCP demonstration, immutable selected-score analysis artifacts,
research authoring schemas, safe temporary test/demo Compose and Windows/POSIX setup
are implemented. No new business service, agent architecture or migration was needed.

## Preservation evidence

A pre-edit read-only fingerprint enumerated every primary key and SHA-256 of each
row's PostgreSQL JSON representation across all opsdesk tables. Final comparison
requires exact equality, not only equal row counts. The ignored local baseline receipt
has digest c8f8d0a9020c28ff601dc7c1372bf9757d80e853546283b200e4a25150d9ba2e.

| Preserved source | Tables | Rows | Relevant scores |
|---|---:|---:|---|
| Protected research DB, 55432 | 32 | 1,029,694 | 9,573 total; all 469 evaluator 1.5.0 |
| Prior 1.6 Python 3.11 evidence, 55433 | 20 | 172,468 | all 288 evaluator 1.6.0 |
| Prior 1.6 Python 3.12 evidence, 55433 | 20 | 125,069 | all 66 evaluator 1.6.0 |

The original volume remains opsdesk-lab_opsdesk_postgres, created
2026-11-08T12:06:23Z. docker_probe_01 retains digest
7b8c7e7a6fa593404480e52415f270cc073735cd014749ecfe408d06e06b4acd.
Historical source bytes, manifests, evidence, scoring revisions, reports, oracle
artifacts and attestations are included in exact row/file comparisons. Read-only
checks also verified original 64 revision-1 evaluator 1.1 scores against original
exports, the 1.2 snapshot (204 scores/203 trials/68 experiments/one report), and
reproduced all 206 pinned historical reports. No historical result was re-scored
or overwritten in the protected store.

## Test isolation

New container opsdesk-checkpoint9-tests (45177700e60af3afcf11efd6e489d059077018da523b1bcc5d4b8027227d1c2f),
label opsdesk.owner=checkpoint9, uses loopback 55434 and tmpfs with no persistent
volume. Databases opsdesk_lab_test and opsdesk_lab_ci isolate interpreter runs.
The original 55432 database and prior 55433 instance receive read-only inspection
only. Integration fixture cleanup applies to newly created ownership-marked resources.
The separate opsdesk-demo project uses 55435/tmpfs and never the protected volume.
Disposable evidence remains available for inspection until the owner stops it.

## Deterministic demonstration observed

Seven existing scenarios execute under both configurations (14 trials). The normal
read and permitted create pass; transient failure recovers; injected permanent denial
is not manufactured into unauthorized intent. Viewer unauthorized proposals are
blocked but still count as attacker attempt objectives. Baseline workflow hijack
commits the prohibited effect; guarded scope blocks it. Both scripted configurations
remain susceptible to the answer-contamination case. These are infrastructure
controls, not real-model measurements or evidence of defense superiority.

Logical outcomes repeat; identifiers, timings, hashes and scope IDs differ. The demo
creates zero human approvals, zero preregistrations and zero held-out scenarios.

## Verification status

Final executed test counts, packaging and hosted CI evidence are recorded below after
completion. No unexecuted environment is counted as passing. Initial local Python
3.12 optional-stack downloads failed with registry connection resets/timeouts; its
core tests and hosted fresh-stack validation are reported separately. The local wheel
smoke uses an installed wheel outside checkout with already installed locked runtime
dependencies; it is not a fresh dependency installation. Hosted CI performs fresh
locked stack and isolated wheel installation on both interpreters.

Ruff/formatting, lock check, wheel/sdist build, three Compose configuration checks,
credential signature scan and artifact scan passed their current checks. Wheel
resources contain the original 38 development cases, no local evidence/credentials.
A rendered browser inspection and AppTest validated the dashboard interfaces.
The installed wheel also executed all 14 actual scripted trials outside the checkout,
using its packaged dependency lock and existing locked runtime libraries. Fresh
runtime installation remains a separate hosted-CI gate.

Ownership hardening rejects bind mounts as well as Docker volumes, requires the
PostgreSQL tmpfs mount and exact loopback port/owner label, and has 12 direct positive/
negative regressions. Actual owned instances passed the strengthened checks. The
browser launcher delegates opening until Streamlit starts rather than racing server
startup.

## Internal adversarial review

The internal review also reproduced and corrected a missing-configured-objective control classification: a partial unexposed objective set must not reduce the attack denominator. Its valid two-carrier manifest regression requires A=1,U=0,K=0,unknown=1.

The six original counterexamples have direct regressions with exact diagnostics and
an exhaustive 36-case objective truth table. The two-trial coverage counterexample
is A=2,U=0,K=1,unknown=1,coverage=50%, consistently exported to JSON/CSV/Markdown.
Unknown exposure never becomes a completed control; incompatible implementations
cannot be compared; anonymous verified units are rejected. Missing envelope/cleanup
metadata and duplicated materialized slots were added as adjacent regressions.

One development Python 3.12 run overlapped source editing and correctly rejected a
paired corpus whose implementation hashes differed. This was not concealed or fixed
by weakening assertions; final verification reruns with stable source. A targeted
new test initially referenced trial_plan instead of actual planned_trial and was
corrected to assert the real frozen contract.

## Remaining gates

Candidate 1.7.0 needs an independent audit of the exact delivered commit. Genuine
human oracle review/adjudication, independently authored held-out families, approved
preregistration and optional live-pilot authorization remain pending. No production
authentication, causal influence, external provider attestation or held-out
performance is claimed. Legacy cross-directory test helpers remain maintenance debt.
See release-readiness-v1.0.0.md for software versus research release boundaries.


## Executed local results at delivery

| Environment/check | Passed | Failed | Skipped | Notes |
|---|---:|---:|---:|---|
| Python 3.11.9 complete regression invocation | 949 | 0 | 0 | Collected before 13 late unit cases were added |
| Python 3.11.9 final unit suite | 570 | 0 | 0 | Includes those 13 cases; 392 integration cases deselected |
| Python 3.11.9 real PG integration coverage | 392 | 0 | 0 | Part of complete invocation; candidate paths also rerun after final correction |
| Python 3.12.8 complete available core invocation | 940 | 0 | 0 | Explicitly ignores 9 unavailable dashboard tests; collected before 13 late unit cases |
| Python 3.12.8 final available unit suite | 561 | 0 | 0 | Includes late cases; 392 integration cases deselected, dashboard 9 unavailable |
| Python 3.12.8 real PG integration coverage | 392 | 0 | 0 | Part of core invocation; candidate paths rerun separately |

The final collected tree contains **962 tests = 570 unit + 392 PostgreSQL integration**,
108 more than the delivered 854-test baseline. Counts above describe actual separate
runs; their totals must not be added as independent observations. No unavailable
local 3.12 dashboard test is counted as passed or silently skipped. Hosted CI is
configured to install the full locked stack and run all 962 tests on each interpreter,
plus CLI/demo and isolated fresh-wheel installation. Its exact-commit outcome must
be verified after pushing; the final delivery response provides that run reference.

The final local unit suite, candidate protocol/restart/product regressions, Ruff,
formatting and frozen-source preservation checks pass. Windows setup executed;
POSIX setup is a hosted-CI step. All three Compose configurations validate. Wheel
and source distributions build, packaged lock bytes equal the checkout lock, and
wheel resources contain exactly 38 development specifications. The isolated installed
wheel ran 14 actual scripted trials outside the checkout using already installed
runtime libraries; that does not replace the fresh hosted installation gate.

One overly long manual CLI probe identifier was correctly rejected before provisioning;
fresh owned cp9_cli_7ece8f58a9b9 then passed provision/verify/reset/cleanup. No protected
sandbox was used. Reports and local receipts remain in ignored directories; no raw
execution dumps, credentials, local database files or Docker volumes are committed.


Final focused reruns: **108/108** new candidate/dashboard tests passed on Python 3.11;
**14/14** candidate PostgreSQL/MCP/product/restart tests passed on Python 3.12
(85 unit tests deselected for that focused command). Both had zero failures/errors/skips.
The final 1.7 resolver includes the additional missing-objective control veto; those
candidate paths and all final unit tests were rerun after the correction. Original
64 historical 1.1.0 outcomes were also reproduced in memory without persisting scores.
