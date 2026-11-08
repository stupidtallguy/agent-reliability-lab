# ADR 0003: Bound stdio MCP servers with host-controlled write identity

- Status: Accepted for Checkpoint 2
- Date: 2026-11-08
- Scope: MCP integration only; the LangGraph agent is deferred to Checkpoint 3

## Context

OpsDesk already has tested permissions, transactions, receipts and state management.
An MCP adapter must preserve those rules while keeping actor, tenant, sandbox and
retry identifiers outside model arguments. Three domains should remain discoverable
without requiring an LLM or exposing an unauthenticated HTTP service.

## Decision

Pin official MCP SDK 2.3.0 and use its public v2 `Server`, `Client`, stdio and
in-memory transports. Choose explicit Server callbacks over the originally
suggested high-level MCPServer decorator layer: they allow flat strict Pydantic
schemas, uniform structured errors and one validation boundary without private
SDK mutation or provisional middleware. Validate both inputs and serialized outputs.

Build three factories with two document, three business and three task tools.
Share the adapter/context/error machinery and delegate all business operations to
unchanged OpsDesk services. Reuse service pagination and write constraints; defer
the earlier planned opaque snapshot-bound cursors instead of inventing new data
access behavior. Keep the versioned envelope, explicit untrusted provenance and
application payload bounds. Protocol framing errors remain distinct from tool errors.

Bind each launch to one existing run and registered synthetic actor/tenant. Hold
a lifecycle lock and verify captured ownership/seed identity across each service
operation, so a replacement sandbox cannot redirect an existing instance. This
launch binding is a trusted-local-host convention, not production authentication.
No administration, SQL, filesystem or arbitrary-network tools are registered.

Trusted client code allocates logical write IDs and signs identity plus arguments
in MCP metadata using a random local HMAC key. The derived service key excludes
arguments so conflicting reuse reaches the existing receipt conflict logic. The
model controls task arguments only. There are no automatic retries or title-based
deduplication. Future agent code must persist IDs, correlate retries and manage reset
boundaries. Reset clears receipts; close servers and retire IDs before resetting.

## Consequences and alternatives

Model-controlled idempotency keys would allow accidental duplicate writes. Unsigned
metadata would leave operation identity selectable by an untrusted caller. A durable
host execution ledger would exceed this checkpoint; signed explicit identities
provide a testable boundary while leaving that limitation visible.

Low-level callbacks require explicit input/output validation and error translation;
real SDK protocol tests verify both. HMAC protects this local host/model boundary,
not a compromised OS account or database owner. Developer stderr is not a model
observation and can contain sensitive diagnostic details. Public HTTP/OAuth, full
attempt tracing, live reset coordination, model adapters and attack injection remain
future work. The development Docker network permits egress (`internal: false`)
to preserve the verified Windows loopback port; security-evaluation isolation needs
a separate tested setup. The networking correction is a separate commit.
