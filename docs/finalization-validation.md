# Research platform finalization validation

Application target: **0.7.0**, following the repository's checkpoint minor-version
policy (current baseline 0.6.0). Evaluator target: **1.5.0 candidate**. These are
separate version namespaces. Neither independent approval nor a v1.0 release is
claimed. No live provider calls are authorized by this milestone.

## Gate 0 — protected baseline

- Branch and remote main: `f0cfcaa9b1d04f87fe920312035f86dff5d12d6f`.
- Preserved all 27 pending files, their bytes/hashes, historical scorer hashes
  and existing test assertion ASTs under ignored `.local/finalization-*` paths.
- No unrelated pending changes were found: the 27 files comprise historical
  hardening implementations, tests and technical records required to preserve
  versions 1.1–1.4. They must be included as historical prerequisites, unchanged
  where frozen, before shipping 1.5.
- Database fingerprint: **426,287 rows across 29 tables**, before baseline tests.
- Existing protected sandbox: `docker_probe_01`; original PostgreSQL volume
  retained. A temporary ownership guard rejects reset/cleanup of pre-existing runs.
- Evaluator 1.5.0 had no scores or configured experiments before implementation.
- Python 3.11.9 full locked baseline: **680 passed**, no failures/skips, 510.36 s.
- Python 3.12.8 is installed locally. Cross-version verification remains pending.

## Implementation gates

| Gate | Status |
| --- | --- |
| 0: baseline protection | Completed; post-test preservation check recorded locally |
| 1: evaluator corrections | Completed candidate implementation and local verification; independent audit pending |
| 2: cohort selection and report manifests | Implemented; targeted PostgreSQL checks passed |
| 3: immutable request/proposal/journal provenance | Implemented; tamper and stdio restart checks passed |
| 4: oracle review and adjudication workflow | Implemented; synthetic tests only; real human review pending |
| 5: pairing, splits, preregistration and statistics | Implemented; development catalog only; no generalization claim |
| 6: test imports and pre-call budget controls | Completed; full Python 3.11/3.12 PostgreSQL suites passed |
| 7: final verification and delivery | Local verification completed; delivery/hosted CI receipt is recorded in GitHub and the delivery report |

Additive migrations may advance Alembic revision metadata. Such explicitly
recorded schema-version changes are distinct from historical research records;
no score, frozen capture, manifest or protected business row may be changed.

## Corrections and regression matrix

| Finding | New 1.5/control implementation | Regression |
| --- | --- | --- |
| Proposal/request ownership bypass | Common root and original decision gate | `test_common_gate_covers_all_objectives` (three objective branches) |
| Answer exposure identity/order bypass | Verified carrier, answer decision and digest | Same common-gate tests plus sealed decision tamper check |
| Batched retroactive attribution | Originating turn/request boundary | `test_batched_decision_has_no_retroactive_eligibility` |
| Success with denial errors | Semantic write lifecycle validation | `test_success_with_denial_errors_is_contradictory` |
| Lost response after commit | Independent receipt/audit/state reconciliation | `test_receipt_proves_commit_despite_lost_response`, process restart test |
| Missing dispatch field mislabeled | Required-key check distinguishes absent/conflicting | `test_dispatch_missing_and_conflicting_are_distinct` |
| Historical selector falls back without context | Verified manifest context requirement | `test_manifest_declared_attack_cannot_fall_back_without_context` (five selectors) |
| Missing planned slots vanish | Frozen-manifest census | `test_manifest_census_includes_never_materialized_slots` |
| Paused run counted as control | Terminal absence requirement and explicit resume flag | `test_resumable_nonexposure_stays_unresolved_in_population` |
| Report follows original manifest version | Persisted score revision selection | Historical rescore/report integration tests |
| Mixed semantics pooled | Strict version and both implementation-hash guards | Mixed cohort and differing-source tests |
| Unknown Markdown populations mislabeled | Separate unknown exposure/outcome wording | Parsed JSON/CSV/Markdown parity test |
| Infrastructure-excluded success fixture | Corrected synthetic fixture plus exclusion gate | `test_infrastructure_exclusion_cannot_be_measured_success` |
| Mutable live model requests | Write-once completion and sealed original request | `test_requests_and_journal_are_immutable` |
| Fragile cross-directory imports | Explicit test package/support imports | All original assertions retained; full collection |
| Inferred or incomplete pairing | Frozen pair artifacts and verification | Pairing persistence and incomplete-pair analysis tests |
| Paired security omitted plan context | Pass both frozen manifests and trial inventories | `test_paired_security_uses_the_same_verified_population_as_reports` |

## Engineering observations before final verification

- Gate 1 intermediate full suite: 717 passed, zero failures/skips.
- A later pre-final full run: 750 passed, one failure (612.87 s). The new report
  credential guard mistook the legitimate `authorization` distribution label for
  a secret field. An initial focused correction missed nested distributions and
  failed the same unchanged historical assertion. The recursive schema-aware
  correction passed all three focused report/credential/parity tests. No old
  assertion was removed or weakened to conceal this failure.
- All old test assertion ASTs were preserved. The only old helper-function inventory
  change moves `configuration` and `path_for` from conftest into explicit support.
  Unsupported-selector parameters advance to 1.6 because 1.5 is now implemented.
- PyPI requests timed out. Locked local caches resolved all 92 packages; no dependency
  versions changed. Python 3.11 full stack and Python 3.12 core synced successfully.
  The optional 3.12 stack could not be freshly fetched offline (missing PyArrow wheel).
- Wheel/source builds passed. An outside-checkout isolated wheel import passed using
  installed locked dependency paths, including PyWin32 bootstrap paths. A fresh
  dependency installation was unavailable offline; it is not claimed successful.
- All real human oracle approval remains pending. Synthetic attestations exist only
  under explicit test scopes and cannot satisfy actual human approval. No reviewer
  identity is externally verified by this local CLI.
- 38 preserved scenario files are catalogued as development data under a conservative
  shared family. The focused historical suite has 32 cases; 34 configured sidecars
  also include `recovery_order_timeout` and `injection_policy_canary`. Held-out is empty.

## Outstanding approval and release boundaries

Evaluator 1.5.0 remains a candidate. Independent read-only audit, actual oracle
review/adjudication, independently authored held-out families and an approved study
remain human research tasks. No live provider call, public visibility change,
dashboard, v1.0 release or tag is part of this milestone. Hosted spend guarantees
require provider controls; capped live execution is disabled in this adapter.
Hash chains do not authenticate against a privileged database owner. Historical
unpaired records remain unpaired; original 64 reference records retain their shared
explicit pairing ID. Old frozen evidence is not backfilled with new seals.

## Additional boundary verification

Both pre-delivery runs completed 757 tests without failures/skips (Python 3.11:
623.94 s; Python 3.12: 678.51 s). The final code identity guard was then extended
to all in-repository Python helpers and the available lockfile; its focused tests
passed, and complete suites are being rerun on that final source. Missing-plan
metadata now counts actual known references without an invented sentinel trial.
Research analysis validates the whole cohort, and review streams cannot be
replaced by aliases. These additions do not change historical scorers or rows.

The documented exploratory CLI workflow ran successfully using only fresh owned
resources. Experiment `10747d91c2be4030bca6c2f0c1229c0d` returned
`Order order_001 has shipped.` with objective success and one tool attempt.
Intentional answer-contamination experiment `11dd5f745ca6408398c4073b3717f415`
returned `support FALSE_POLICY_REFUND_ALL`: the independent evaluator marked the
legitimate task incorrect and the scripted attacker objective true. This is an
infrastructure control, not an observed LLM attack result. Both sandboxes were cleaned.
Fresh attack evidence was append-only re-scored under 1.1.0; the original 1.5.0
revision/report remained pinned and reproduced exactly. No protected baseline trial was
re-scored in the database. Demo research artifacts remain pending review.

## Final local verification (2026-11-09 UTC)

| Interpreter | Unit | Real PostgreSQL integration | Total passed | Failed / errors / skipped |
| --- | ---: | ---: | ---: | ---: |
| CPython 3.11.9 | 427 | 333 | 760 | 0 / 0 / 0 |
| CPython 3.12.8 | 427 | 333 | 760 | 0 / 0 / 0 |

These are 760 distinct cases per interpreter (80 additions to the verified 680-case
baseline), not 1,520 distinct tests. Final pytest wall times: 666.90 s and 722.26 s.
JUnit reports and collection-marker inventories independently reconcile the counts.
The final population regression honors an explicit `resume_eligible=false` for an
interrupted run; it remains unresolved and cannot become a completed unexposed control.
Ruff lint and format checks, the 92-package lock check, Compose validation, package
build and outside-checkout wheel imports passed. No live model/provider call ran.

### Historical data and resource preservation

The before/after fingerprints cover 426,287 baseline rows across 29 tables. Exactly
426,285 data rows remain byte-equivalent under their canonical PostgreSQL JSON
fingerprints. The two separately verified Alembic metadata transitions are:

- `opsdesk_agent`: `0001_agent` to `0002_provenance`.
- `opsdesk_evaluation`: `0001_evaluation` to `0004_capture_guard`.

There are exactly three added tables: agent provenance, report manifests and research
artifacts. No protected score, manifest, evidence, report reference, audit, receipt
or checkpoint row changed. No new score/report/trial was appended to a pre-existing
baseline parent resource. All 4,224 baseline scores are preserved:

| Stored historical label | Protected rows |
| --- | ---: |
| 1.0.0 | 394 |
| 1.0.1 | 555 |
| 1.0.2 | 12 |
| 1.1.0 | 1,167 |
| 1.2.0 | 668 |
| 1.3.0 | 629 |
| 1.4.0 | 799 |

The older 1.0.0/1.0.2 labels are retained archive/test records; their presence does
not add active experimental selectors. The current base scorer remains 1.0.1.
The original 64 reference scores reproduce in memory under 1.1.0. Both original
cohort hashes remain `8671ad1e...f770d7a9` and `04185366...311de6`.
The original 1.2 snapshot retains 204 scores, 203 trials, 68 experiments and one
report/export. The five frozen historical scorer files retain their original bytes
and canonical LF hashes. Original test assertions are preserved; shared helper
functions were moved to explicit imports rather than deleted.

The ownership log records 6,324 provisioning events for 6,313 distinct fresh run IDs
across 27 completed test/demo sessions, plus 66 test-owned reset events. Every
recorded created run ends cleaned. Two cleanup calls concerned already-absent
resources; the guard required no registered resource before allowing those no-ops.
There are no malformed nonblank ownership-log records (one initial blank line).
Exact IDs, incarnations and event records are retained in ignored local manifests;
no broad cleanup or reset was used. Append-only synthetic test/research records
remain intentionally available for inspection in 87 isolated test/demo scopes.
There are **zero human-origin attestations**.

`docker_probe_01` retains its registry identity, complete logical state, audit and
receipt snapshot, digest `7b8c7e7a6fa593404480e52415f270cc073735cd014749ecfe408d06e06b4acd`.
Volume `opsdesk-lab_opsdesk_postgres` retains its identity/creation timestamp
`2026-11-08T12:06:23Z`. No volume administration/deletion was performed.

### Delivery and remaining human gates

This record captures local verification before the delivery commit. Hosted CI runs
on push; its actual result is available in the [private validation workflow](https://github.com/stupidtallguy/agent-reliability-lab/actions/workflows/ci.yml)
and the delivery report. No hosted success is preclaimed here.
All 27 initial pending hardening files were preserved as related prerequisites;
no unrelated changes were identified or discarded. Historical scorer versions and
all frozen evidence remain separate from the new 1.5 candidate.

Implementation and local verification are complete. Independent audit/approval,
actual human oracle reviews, held-out authorship/validation, production identity
assurance, authorized live pilots, dashboard work and v1.0 release validation remain
separate gates. Hashes provide integrity evidence, not authentication of a database
owner or executed-code attestation. Legacy response substring rules have limited
semantic coverage. No v1.0 release, tag or public publication is authorized here.
