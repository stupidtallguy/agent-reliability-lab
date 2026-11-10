# Remediation of the read-only 1.5 audit

Audit target: c2b7912456fab61e398d0fdad044bca96602e1e7 (application 0.7.0).
Correction: application 0.8.0, explicit evaluator 1.6.0 candidate. The audit was
provided in the conversation; this document is an implementation response, not an
independent audit attestation.

| Finding | Root cause | Correction | Direct regression |
| --- | --- | --- | --- |
| AUD15-01 | Intent iteration required operation DTOs | Inspect sealed completed decisions before validation | `test_original_sealed_proposal_survives_prevalidation_boundary`, real interruption and original-intent tests |
| AUD15-02 | Read carriers omitted status/error/effect reconciliation | Common physical attempt/response validator | `test_carrier_lifecycle_corruptions_have_specific_diagnostics`, missing completion test |
| AUD15-03 | Captured model configuration not compared to sealed requests | Candidate-only provider/model identity projection | `test_each_identity_boundary_has_specific_diagnostic`, scoring-path identity test |
| AUD15-04 | Population assumed complete execution dictionaries | Defensive typed boundary facts and retained manifest slots | `test_malformed_execution_cannot_remove_manifest_slots`, integrity/exclusion tests |
| AUD15-05 | Two independent trial outcome interpretations | One versioned contradiction-veto ANY resolver | Canonical policy, denominator and export parity tests |
| AUD15-06 | Latest scores not checked against pinned oracle | Explicit revision selection and exact oracle/scenario checks | `test_changed_oracle_cannot_be_an_agent_effect`, historical revision replay |
| AUD15-07 | Only pair artifact IDs were unique | Trial and execution unit validation with structured exclusions | `test_underlying_units_cannot_be_aliased`, persisted alias test |
| AUD15-08 | Disjointness was local to one manifest | Composite hash-pinned dataset-release validation | `test_registered_partitions_are_validated_together`, release immutability test |

Historical scorer/projection files are not edited. New candidate modules, routing
branches and renderer selection preserve the original selectors and report inputs.
The few old unsupported-selector parameters move from 1.6 to 1.7 because 1.6 is now
implemented; assertions are retained. Synthetic accounting helpers move into an
explicit support module; tests do not import other test modules or conftest helpers.

Precise corruption diagnostics are asserted. Where the broad reconciler necessarily
vetoes first, direct production-gate assertions also isolate the intended invariant.
Outer seals are re-created only in memory in specific corruption tests to exercise
relationship checks rather than merely detecting an unchanged digest.

No new human approval, held-out example, attack category, model provider, dashboard
or production authentication is introduced. See [semantics](evaluator-1.6.md) and
[execution receipts](checkpoint-8-validation.md). Independent approval is pending.
