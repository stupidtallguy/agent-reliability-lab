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
