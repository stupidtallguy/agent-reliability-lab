# Security model

The v1.0.0 demo and test launchers pin the Compose project and packaged file. They
verify owner, Compose project/service labels, tmpfs, and loopback port before
operating on an existing container. The Docker daemon and CLI environment remain
trusted local operator infrastructure. The dashboard never executes those commands.

Trusted host configuration fixes actor, tenant, scenario/run binding, tool scopes,
model configuration and budgets. Model prompts, retrieved documents, tool responses
and final answers cannot grant permissions. MCP handlers call the existing validated
service layer; both agent configurations share default-deny authorization, atomic
writes, optimistic versions and host-bound idempotency metadata. Agent tools expose
no arbitrary SQL or filesystem operations.

The dashboard has a separate read-only connection boundary, no mutation controls,
and bounded/redacted data previews. It binds only to 127.0.0.1. Use a SELECT-only
role for deployment defense in depth; transaction read-only mode is not a substitute
for production identity/access management. Temporary test/demo trust authentication
is limited to named loopback-only synthetic instances with tmpfs and ownership checks.

Seals and hash chains detect inconsistencies relative to trusted local evidence.
An administrator with database/control-plane privileges can rewrite data and seals;
local hashes prove neither remote provider execution nor causal attack influence.
The evaluator separates verified effects from uncertain attribution and preserves
unknown/contradictory/incomplete states. Historical versions remain reproducible,
including their known limitations. See threat-model.md, evaluator-1.7.md and
release-readiness-v1.0.0.md for boundaries and pending independent review.
