# Reproduction and integrity

Use the committed lockfile, exact source commit plus source hashes, CPython 3.11 or
3.12 and the pinned PostgreSQL Compose image. [Installation](installation.md)
describes environment setup. Do not run paid models during reproduction.

Each trial starts from a fresh registered schema. The logical fixture hash is
independent of physical run identifiers. Ownership markers guard cleanup. Never
reset an active or pre-existing run, `docker_probe_01`, or the persistent volume.

New executions seal original request hashes, template/tool schema hashes, model
identity/parameters, source commit, original decisions, raw bounded/redacted proposal
strings, normalized operations, physical responses and journal events. Records bind
execution, sequence, kind/reference, body hash and previous hash. Database triggers
reject journal/provenance updates/deletes and permit a model request to complete
only once. Original proposal and validated arguments remain distinct. Complete
provider wire payloads are not retained; redaction and bounds are deliberate.

Frozen evidence retains these seals and its collector projection. Verification
detects changed/deleted/reordered records, inconsistent identities and altered
projections. A privileged database owner can disable triggers and recompute hashes;
this is tamper evidence, not cryptographic authentication or external notarization.
Old executions are not backfilled. Resuming an old unsealed prefix cannot establish
new immutable history retroactively and is explicitly unsupported for that claim.

Scores append revisions. Reports pin selected scoring IDs/revisions and hashes,
manifest, rules, implementation and renderer. Mixed cohorts fail by default.
`reporting.reproduce(store, report_id)` uses persisted inputs without migrations or
new scores. Identical substantive inputs reproduce the same content hash; report
IDs and generation times intentionally differ. Old exports without report manifests
remain preserved; they are not falsely labeled reproducible by the new renderer.

`benchmarks/research/historical-scorers.json` pins canonical LF hashes for historical
scorer files across Windows/Linux checkouts. The preservation API can compare
per-primary-key database fingerprints. An additive migration may change only its
explicit Alembic version row; this is reported separately from historical data.
Local before/after fingerprints and resource ownership logs stay ignored because
they include local identifiers. No raw research traces or secrets are committed.

Hard-budget options `max_known_tokens` and `max_estimated_cost` check before another
model call. A scripted adapter can reserve a bound only with explicit nonnegative
usage for every possible branch. Unknown usage, unresolved requests or missing
versioned exact-model prices stop capped execution. Actual hosted input/spending
reservations are unavailable in this adapter; capped live calls are disabled rather
than advertised as guaranteed. Uncapped opt-in live usage retains the historical
post-hoc accounting semantics. Scenario accounting limits are not provider spending
guarantees. Model/tool call, output, context, retry and wall-clock limits also apply;
already-dispatched remote operations cannot universally be cancelled.

Scripted canonical re-execution and frozen evidence re-scoring do not measure live
model reliability, invoice cost or counterfactual behavior. Fixed hosted parameters
do not guarantee deterministic responses. Independent oracle review, externally
audited evaluator approval and held-out studies remain human research tasks.


## Checkpoint 9 extension (0.9.0)

Candidate 1.7 requires exact dataset release, oracle/score revisions and complete compatible implementation identities for verified comparison. Anonymous mathematical summaries are explicitly unverified. Dashboard downloads render pinned reports without writes. Historical renderer 2.0.0/2.1.0 reproductions route to the byte-preserved legacy renderer; candidate output uses 2.2.0. See demo-guide.md for repeatable logical scripted outcomes and varying physical IDs/timing.
