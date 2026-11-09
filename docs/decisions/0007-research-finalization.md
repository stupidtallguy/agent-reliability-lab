# ADR 0007 — Versioned provenance, reports and research controls

Status: implemented candidate; independent evaluation and human reviews pending.

The 1.4 audit found inconsistent objective provenance, contradictory write status,
missing-field classification, context fallback and population/report routing defects.
Correct them in separate evaluator 1.5.0; preserve historical scorer bytes and scores.
Application 0.7.0 follows the existing checkpoint minor-version policy. Default
experimental selection remains 1.1.0.

Use a shared objective provenance gate, strict semantic lifecycle checks and
manifest-derived planned slots. Immutable report manifests pin explicit scoring
revisions; reject mixed evaluator/implementation cohorts. Cross-version outputs stay
separate. These choices favor explicit unknowns over unsupported success or failure.

Add execution seals and write-once decision guards through additive migrations,
without backfilling historical history. Hash chains provide tamper evidence, not
authenticity against a database owner. Preserve full bounded/redacted parsed model
decisions separately from validation and normalized operations.

Store typed research artifacts as append-only JSON with hash-pinned references,
instead of a new service/framework. Reviewer identities remain declared/unverified;
synthetic tests cannot approve oracles. Frozen study gates validate input bindings
before execution. Pairing requires explicit IDs and frozen matching inputs. All
existing templates stay development data in one conservative family; held-out is
empty pending independently authored content. Cluster-aware summaries make no
development-sample superiority claim. Read-only views prepare a future dashboard.

Tradeoffs: local human attestations need external identity assurance; no production
HTTP auth or oracle discovery is added. Existing historical unpaired data stays
unpaired. Hosted token/cost reservations are unsupported, so capped live calls fail
closed. No new dependency or dashboard is needed for these controls.
