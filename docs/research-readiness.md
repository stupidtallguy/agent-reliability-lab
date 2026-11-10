# Research controls and pending human work

Application 0.7.0 provides research infrastructure, not independent review or a
validated confirmatory study. `opsdesk-research` is a trusted developer CLI. It does
not authenticate people. Research objects are JSON-schema-compatible Pydantic
contracts stored as immutable, hash-pinned, consecutively versioned artifacts in
`opsdesk_evaluation.research_artifacts`. Scopes isolate test/demo records; no agent
MCP tool can access these records.

## Oracle review

An oracle records scenario/version/hash, legitimate/prohibited behavior, state,
response and trace assertions, attacker objective, evidence requirements, metric
eligibility and executable scoring sidecar. Its initial status is pending. Editing
an oracle appends a version; earlier results retain their original rules hash.

Reviewers declare identity, affiliation, role, conflicts and active status. Identity
assurance is always `declared_unverified`. Attestations pin both oracle and reviewer
versions/hashes, decision, disagreement class, rationale, evidence and timestamp.
An actual human must explicitly submit `--human-attestation`; software never creates
one automatically. Synthetic attestations are confined to test/demo scopes and
cannot satisfy human approval. No real reviewers or approvals are seeded.

Two distinct, non-author, active reviewers must declare no conflict. Material
disagreement remains unresolved. An adjudicator must have the right role, be distinct
from reviewers and author, and pin the current review hashes. New reviews invalidate
an older resolution's applicability. Approval means declared human review, never
externally verified identity. This local workflow needs organizational identity
verification before use for higher-assurance research.

## Frozen study and amendment workflow

Preregistrations pin the question/hypotheses, outcomes, model/configurations,
population/categories/allocation, pairing, oracle/evaluator/split references,
exclusions, missingness, analysis/intervals/comparisons, stopping rules and budgets.
Amendments append a reason, changed fields, author, timestamp, parent reference and
confirmatory impact. They never edit a preregistration. Amended confirmatory studies
need a new registration before execution.

`ExperimentConfig.study` optionally binds a frozen reference and scope. The runner
checks population/content hashes, exact model, configuration, sample size, budgets,
oracle rules and selected evaluator before creating an experiment. Confirmatory
runs additionally require approved declared-human reviews, explicit host acceptance
of identity assurance and an external evaluator-audit reference. Scripted fake-model
trials cannot be confirmatory evidence about an LLM. Evaluator 1.5.0 has not received
that external audit; this implementation does not create an approval.

## Explicit pairing

Pair artifacts record pair/group IDs, baseline and guarded trial IDs, intended
defense difference, pinned oracle, verified criteria and exclusions. Verification
reads frozen manifests/captures and requires an explicit shared pairing ID, matching
scenario/version/hash, trial index (deterministic fixture trial seed), initial state,
fixture/seed hashes, model, parameters, budgets, harness/payloads, evaluator, oracle
and environment/source hashes. A missing counterpart stays incomplete. Similar
names are insufficient. Historical unpaired records are never assigned inferred IDs.

## Splits and statistics

The catalog records template/family, mechanism, lineage, split and content hash.
All 38 existing scenario files remain development data. A conservative shared family
prevents claiming independence among related OpsDesk templates; the separate held-out
manifest is empty. The focused historical suite has 32 cases; its runtime sidecars
may configure original scenarios too. No content is moved or regenerated.

Split validation rejects any semantic family crossing boundaries regardless of
different text hashes. Newly independently authored held-out families require human
review and freezing before any held-out access. The current runner continues to
exclude held-out execution; no tuning or validated generalization is claimed.

Analysis resolves persisted pair and scoring references and returns selected revision
IDs/hashes. Unknown/missing pairs are excluded from measured outcomes but reported
in pair coverage and worst-case exclusion sensitivity bounds. Descriptive paired
risk differences use complete verified pairs. Family-weighted differences average
family means; a seeded percentile cluster bootstrap resamples families (default
2,000 draws), and requires at least two families. Wilson intervals are descriptive
when repeated observations are clustered. Exact two-sided McNemar conditions on
discordants, `min(1, 2*BinomialCDF(min(b,c), b+c, 0.5))`; the lower-level function
requires an explicit independent-unit justification and one complete pair per family.
The persisted analysis workflow conservatively leaves this inferential test disabled.
Tiny development samples support no superiority claims.

## Commands

Configure PostgreSQL as in [installation](installation.md), then:

```console
uv run --locked opsdesk-research init
uv run --locked opsdesk-research validate benchmarks/research/split-development.json
uv run --locked opsdesk-research --scope demo_research_examples append benchmarks/research/split-development.json
uv run --locked opsdesk-research --scope demo_research_examples append benchmarks/research/example-oracle.json
uv run --locked opsdesk-research --scope demo_research_examples append benchmarks/research/example-preregistration.json
uv run --locked opsdesk-eval run benchmarks/development/normal_order_status.json --config benchmarks/research/example-experiment.json
uv run --locked opsdesk-research --scope demo_research_examples list --kind oracle
```

These examples are explicitly exploratory infrastructure specifications with pending
reviews. Append commands reject reusing an existing version; inspect existing scope
before rerunning. Capture the printed references for `review-status`, `verify-pair`
or `analyze` input files. Analysis JSON contains `pairs` (hash-pinned references),
`split` reference and `evaluator_version`; `--seed` controls resampling.

`ResearchView.rows` exposes bounded, deterministic, PostgreSQL-read-only queries
for experiments, trials, scoring revisions, reports, research objects, journal and
provenance. It performs no migrations, scoring, writes or cleanup. No dashboard is
built; presentation must stay separate from scoring and trusted administration.

Review streams are unique per oracle/reviewer; adjudication streams are unique per
oracle. Alternate IDs cannot revive a stale decision. Versions append under a
scope advisory lock. Study manifests retain the review references/statuses observed
before execution. Analysis rejects incompatible pair groups, configurations,
environments and scoring implementation identities; it does not pool them silently.

## 0.8.0 corrective controls

Paired analysis now checks each selected scoring revision against the pair's pinned
oracle rules, scenario/version/hash, evidence and execution. Multiple matching scores
require `score_selections` keyed by trial ID, with `scoring_id` and/or `revision`.
Analysis outputs pin every selected revision. Aliases/reused trials/executions raise
a structured experimental-unit error with exclusion reasons; implicit weighting or
shared-control repeated-measures designs are unsupported. Distinct repeated trials
remain clustered descriptive observations, not automatically independent samples.

`dataset_release` artifacts pin both development and held-out references plus their
complete assignments and validation version. Registration verifies family/template/
scenario disjointness across partitions and detects hash substitution. Confirmatory
studies must reference a composite release; historical development-only exploratory
split references remain supported. The checked-in release has 38 development records
and zero held-out records. Labels cannot prove semantic independence; human curation
and review are still needed.

After registering both existing split manifests in a chosen scope, register
`benchmarks/research/dataset-release.json`; `opsdesk-research --scope SCOPE verify-release`
accepts the same release file and reads its pinned partitions without writing.
Analysis JSON can provide `score_selections`, for example
`{"TRIAL_ID":{"revision":1}}`. Explicit `evaluator_versions` comparisons require
`comparison_policy=separate_pinned_oracle_cohorts_v1` and produce separate cohorts;
they never pool incompatible semantics or claim equal scoring behavior.
