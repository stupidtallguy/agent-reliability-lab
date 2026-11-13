# Preregistration and amendments

The exported Preregistration schema includes research questions/hypotheses, primary
and secondary metrics, scenario population, conditions, split/oracle references,
sample-size rationale, statistical methods, exclusions and missing-data handling.
Use templates/README.md and statistical-methodology.md to author a real study before
collecting confirmatory results. A generated JSON schema is not an approved study.
The [OpsDesk preregistration draft](preregistration-draft.md) documents the proposed
estimands and open study decisions without registering a study.

Validate a completed authorized specification with `opsdesk-research validate FILE`.
Register through the trusted scoped `append FILE` workflow. Registration preserves
its exact body/hash; revisions and amendments append references and reasons rather
than updating it. Amended confirmatory studies require a new preregistration before
execution. Pin evaluator audit evidence, dataset release and oracle reviews.

Exploratory scripted demonstrations remain explicitly exploratory and create no
preregistration approval. Confirmatory execution checks declared review status and
requires explicit host acceptance of its unverified identity assurance. Genuine
human approval, sample-size judgment and any paid/live-model authorization remain
outside automated code. Optional live evaluations require their existing separate
explicit opt-in. The software release verification used scripted execution only.
