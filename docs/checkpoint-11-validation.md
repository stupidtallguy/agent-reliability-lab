# Checkpoint 11 validation

The reliability branch starts from the merged Tech Modern dashboard commit
`6fe567a61a7391b27166dbac0583bc0be833f8e7`. Application 1.0.0, experimental
default 1.1.0, candidate evaluator 1.7.0 and renderer 2.2.0 retain their existing
semantics. The reliability report has its own version, `reliability-1.0.0`.

## Reproduction

Use the [contract audit](reliability-contracts.md), [retry test matrix](retry-concurrency-lab.md)
and [demo guide](reliability-demo.md). The PostgreSQL tests require an owned
ephemeral instance. For Windows and Linux, the instructions are in
[installation](installation.md).

```text
uv lock --check
uv run --locked --extra stack opsdesk-lab test
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
uv run --locked --extra stack opsdesk-lab reliability-demo --no-ui
```

The development demo observed one logical notification, two physical MCP
attempts, one receipt, one committed intent and two synthetic provider
submissions. Revision 1 retained unknown delivery after acceptance. Revision 2
appended a delivery callback. The review inspected both revisions and the Retry
Inspector in a live Streamlit session and checked that all three export controls
were available. Package and benchmark scoring remain separate from the synthetic
demonstration.

The protected PostgreSQL container remained stopped throughout testing. The
persistent volume was mounted read-only to hash its files. Before and after,
the file-manifest digest was
`26322a573fe0a3d3666784d745d67085186c08a822b8d39203ed24974108656f`.
The logical database snapshot was not queried. The physical fingerprint is
separate from a query-based sandbox digest.

Engineering verification covers the local evidence chain and artificial fault
boundaries. This checkpoint introduces no live-model research results.

## Checkpoint 11.1

Operational metric version `reliability-1.1.0` uses distinct, explicitly
eligible observations. For recovery, deduplication, and conflict rejection,
the denominator includes only resolved eligible faults, replays, or conflicts.
Missing or contradictory resolutions remain visible as unresolved. Mutation
counts are based on the observed write inventory. Zero is a valid mutation
count when the inventory establishes non-commitment. An absent inventory leaves
commitment unknown and prevents a duplicate-effect measurement. For pinned
trials, chain completeness measures inspected chains, while outcome coverage
continues to include all materialized rows.

The disposable reliability schema adds provider bindings, issued events, and
append-only callback conflicts during explicit simulator registration. Older
provider rows lack this authority and cannot establish new verified delivery.
Existing reports retain their stored bytes and use their original formatter.
New reports pin the agent ledger, local receipt, provider evidence, and the
consecutive predecessor. The reader validates ancestry even when limiting
the number of returned revisions.

## Checkpoint 11.2 evidence publication

Current reports use operational metric version `reliability-1.2.0`.
Publication takes the per-execution revision lock and the notification lock
before checking the source tables. PostgreSQL SHARE locks acquired with NOWAIT
protect the checks from concurrent direct SQL writes until the report and its
append-only evidence snapshot commit. Writers holding incompatible locks cause
publication to fail with a retryable PostgreSQL lock error.

The publisher independently verifies the committed intent, outbox and provider
records. It pins the mutation inventory and attempt projection. Retry outcomes
join the original proposal, dispatch and completion journal entries, sealed
responses and the demo's sealed pre-retry receipt observation. Metrics are
generated from that evidence. If a caller supplies metrics, canonical equality
is required. Readers recompute the metrics and verify the evidence digest,
execution binding and full revision ancestry. An exact replay returns the
prior frozen observation.

Prior metric versions retain their original renderers and bytes. Database
records require a matching execution and owned notification receipt even for
historical access. Historical records carry an out-of-band unverified label and
remain available for download. The version string does not confer current
verification. The supported write path publishes only the current version.

Context verification checks required fingerprint types and formats and follows
the intervening sealed model requests and decisions. The task Retry Inspector
requires a matching sealed successful attempt, receipt and independent mutation
audit before displaying verified commitment. The observation label requires
an audit row in the execution's actor and tenant scope. It can still show a
mutation on the target when its attribution to the operation is unresolved.

## Checkpoint 11.3 authenticated publication

The publisher uses Ed25519 with an operator-managed private key outside
PostgreSQL. The attestation schema is `opsdesk-reliability-publication/1.0.0`.
New reports use operational metrics `reliability-1.3.0`. A positive retry
deduplication or recovery measurement now requires a resolved physical retry,
exactly one observed local mutation, and reconciliation of the corresponding
receipt. Incompatible known observations are contradictory. Missing required
evidence leaves the measurement unavailable.

The authenticated manifest binds the execution, original logical operation,
notification, report ID, revision and predecessor to the report contents,
canonical metrics, and frozen evidence digests. The boundary includes the sealed
execution ledger head and the complete provider population collected under the
existing publication locks. One transaction inserts the document, frozen
observations and attestation. The public verification key comes from a
configured trust directory. A database writer cannot choose that directory or
authenticate a new revision by hashing, copying or editing rows.

The reader verifies the signed snapshot and its ancestry. A separate read-only
query compares the signed observation to live records for presentation.
An ordinary later event advances current state. A conflicting callback or
mutated provider payload is shown separately as a current inconsistency.
An invalid successor is excluded with a visible warning. Earlier authenticated
revisions remain available. Unsigned versions 1.0.0 through 1.2.0 retain their
original export format and historical unverified status.

The publisher and Retry Inspector reconcile the logical terminal status with
the sealed attempt and response. A failed status conflicting with a sealed
success remains visible alongside any independently observed mutation.
An acknowledgment failure can leave a real effect and unresolved logical
commitment. A later unsuccessful physical retry does not erase a supported
successful logical result.

See the [demo guide](reliability-demo.md) for key configuration. Rotate by
generating a distinct private file in the existing trust directory and changing
the publisher's private-file setting. Keep retired public files to verify old
reports. Removing a public file withdraws trust and makes those signatures
unverifiable. The dashboard and MCP tool process receive no signing-key
configuration from the launcher. CI generates disposable identities.

This trust model assumes the publisher process and trust directory remain
under operator control. An authorized signature authenticates the bounded
publication, including its pinned observations. The publisher remains
responsible for collecting and validating those observations. A compromised
signer or manipulated source records that mislead the publisher before signing
fall outside this guarantee. A database owner can withhold or delete a
legitimate signed history. Detecting rollback to an older signed prefix
requires an independently pinned head, which this local workflow lacks.

## Checkpoint 11.5 evidence identity

The baseline at `b30364b` credited attempt 2 when the second physical
attempt failed before MCP and attempt 3 actually returned the receipt.
A connection-failure variant also replaced the verified retry observation
with an unresolved one. The same baseline labelled a signed report current
after its live successful attempt was changed to permission denied. Its
ordinary trial view paired a rehashed trial with a score pinned to the
previous capture.

Operational version `reliability-1.4.0` derives receipt reuse from a sealed
matching receipt response on the actual successful retry and a scoped receipt
observation within the earlier fault's dispatch and response boundaries.
Timeout and transport faults keep their own attempt IDs, ordinals and ledger
references. Faults without adequate receipts remain unresolved. A verified
retry is counted once by its attempt ID even when multiple faults refer to it.
Historical signed `reliability-1.3.0` reports still verify and render using
their original metric semantics. The Ed25519 attestation schema is unchanged.

Current-source comparison uses the captured attempt inventory, the sealed
ledger and the live journal in addition to the operation, local receipt and
provider population. Changed historical facts are flagged with an evidence
reference. Consistent later observations and unavailable queries have
distinct states. These labels are presentation metadata and never modify an
authenticated observation or its exports.

The ordinary trial view checks the selected score revision's evidence hash
against the stored and recomputed trial hash before showing score-backed
results. A mismatched trial and score retain separate references for inspection.
The Retry Inspector also requires the audit row and audit payload to identify
the task in the scoped receipt. Historical evaluator records are preserved.

Run the PostgreSQL regressions in an isolated test database. The two
three-attempt variants interrupt the second dispatch before invoking MCP.
The trial integrity regression changes only the disposable capture while
preserving the earlier materialized score. These probes verify the product's
evidence checks under privileged test writes.

The demo retries transient PostgreSQL lock conflicts with bounded backoff.
Each attempt opens a new publication transaction and validates the sources
again. The publisher itself retains fail-fast locks and rejects permanent
evidence conflicts.
