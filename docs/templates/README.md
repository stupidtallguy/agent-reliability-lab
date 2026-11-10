# Human research authoring workspace

Export current machine-readable schemas and a practical checklist:

```console
uv run --locked opsdesk-lab review-workspace .local/review
uv run --locked opsdesk-research validate YOUR_ARTIFACT.json
```

The export creates no database records or approvals. The trusted research CLI
registers immutable artifacts only after an authorized person supplies real content.

## Independent held-out family authoring

1. Author workflows independently from development templates; record author/process
   provenance and exclusions. Do not paraphrase the existing 38 cases.
2. Assign new template and family IDs, version and hash the exact scenario/fixture.
3. Independently review state, response, trace and prohibited-effect oracles.
4. Register immutable development and held-out manifests, then one composite dataset
   release pinning both hashes. Validate all partitions together.
5. Keep the current held-out manifest empty until legitimate reviewed families exist.

## Preregistration outline

Record research question; primary and secondary hypotheses; estimands; population;
conditions and pairing; dataset/oracle/evaluator hashes; sample-size rationale;
cluster unit; statistical methods/uncertainty; missing-data sensitivity; exclusion
rules; stopping rules; authorization and registration date. Amendments append a new
version with a reason; they never rewrite the original. A generated template is not
a preregistered or approved study.

## Oracle review outline

Review legitimate task outcomes, protected targets, permitted changes, forbidden
changes, multiple valid solution paths, negative controls, temporal exposure,
unknown evidence, metric eligibility and denominator rules. Declare conflicts and
identity, pin exact specification hashes and preserve dissent. Synthetic attestations
cannot satisfy human approval; declared human identities still need external verification.
