# ADR 0008: Candidate-only hardening and a read-only local product

Status: accepted for implementation; evaluator approval pending independent audit.

Use new 1.7 attribution/projection/population modules and renderer 2.2.0. Retain the
old renderer in a legacy module so pinned 2.0/2.1 reports reproduce. Keep 1.1.0 as
experimental default. No historical migration or scoring revision is edited.

Use Streamlit from the existing optional stack, PostgreSQL read-only transactions
and existing ResearchView methods. A trusted CLI owns mutations and the deterministic
actual-agent/MCP demo. Dedicated labeled tmpfs Compose projects avoid protected data.
Keep review/held-out/preregistration authoring separate from genuine human approval.

Freeze selected-score analyses in the existing generic immutable research artifact
store. Require oracle/dataset/revision/implementation compatibility and unique units.
Separate not-applicable metric pairs from missing in-scope outcomes. Anonymous math
has an explicit unverified mode without inferential claims.

Tradeoffs: tmpfs demo evidence must be exported before stopping; the local dashboard
has no production authentication; historical implementations deliberately retain old
semantics; current development scripts provide no live-model or held-out conclusion.
