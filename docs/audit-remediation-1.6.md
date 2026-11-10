# AUD16 remediation record

These are implementation changes and internal verification, not independent approval.
Historical 1.6 semantics remain frozen; corrections are explicit 1.7.0 candidates.

| Finding | Root cause | Correction | Direct regression |
|---|---|---|---|
| AUD16-01 | Logical read status was not reconciled to successful physical attempts | Candidate logical lifecycle gate before attribution | `test_read_logical_state_conflict_is_not_success` (failed/rejected/pending/retry) |
| AUD16-02 | Existing seals did not validate input/hash/order joins | Candidate projection v3 checks ledger and journal boundaries | `test_sealed_request_relationships`; stdio and process restart controls |
| AUD16-03 | False exposure plus successful outcome could become U | Exhaustive cross-field truth table and contradiction veto v2 | `test_complete_objective_truth_table`, `test_audit_two_trial_control_corruption_and_export_parity` |
| AUD16-04 | Missing identity fields were filtered out | Version-aware mandatory hash/scope requirements | `test_required_candidate_and_historical_identity`, invalid-present hash tests |
| AUD16-05 | Unchecked envelope and manifest shapes raised exceptions | Typed manifest boundary, retained inventory and null plan counts | `test_malformed_manifest_is_typed_and_reported`, malformed execution population tests |
| AUD16-06 | Unit validation ran only when some IDs existed | Always validate verified underlying trial/execution units | `test_identity_free_observations_have_no_verified_or_inferential_mode` |

Adjacent changes: pure report downloads, malformed raw capture rescoring, distinct
not-applicable paired estimands, immutable exact-score analysis artifacts, and safe
local product/test workflows. No historical benchmark specification is modified.
The original 38 scenarios remain development data and the held-out partition is empty.
See checkpoint-9-validation.md for executed results and preservation evidence.

Internal review additionally separated paired metric scope from observed eligibility: a configured attack with infrastructure failure remains unknown, not not-applicable. Scope is derived from the frozen planned-trial metadata. Duplicate materialized slot aliases cannot choose a successful record for attack attribution. Both have direct regressions.

A further internal population probe found that a completed unexposed objective could incorrectly make an entire trial a control when another configured objective was missing. Candidate 1.7 now requires no unresolved objective-set errors before assigning U. The regression uses two valid injection specifications on distinct carrier tools and verifies A=1,U=0,K=0,unknown=1,coverage=0.
