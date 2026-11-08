# OpsDesk MCP tool contracts v1.0

Checkpoint 3 uses these unchanged discovery contracts through existing clients.
Provider schemas derive from discovery, never manual duplicates. Local validation
and bounded capture supplement server enforcement. Identity and write IDs stay
host-controlled. Durable proposal IDs differ from attempts and logical writes;
see [agent execution](agent-execution.md). Tool outcomes do not establish objective
task success.

Implemented in Checkpoint 2 with official MCP SDK 2.3.0. Tools use flat strict JSON
arguments and a typed envelope. All business rules remain in the existing service
layer. See [MCP integration](mcp-integration.md) for launch/client commands and
[database contracts](database.md) for authorization, transactions and isolation.

## Discovery and input contracts

IDs match `[a-z][a-z0-9_-]{1,63}`. Inputs reject extra properties and scalar
coercion; strings are trimmed and must remain nonempty. Limits are inclusive.
No tool accepts actor, tenant, run, approval, operation or idempotency identities.
Optional pagination uses existing service `after_id` keys and ascending record ID.
It is not snapshot-bound opaque pagination; callers must coordinate concurrent
changes if a stable cross-page snapshot is required. Discovery itself has no
pagination because each server exposes at most three fixed tools.

| Server/tool | Required arguments | Optional arguments | Successful `data` type |
| --- | --- | --- | --- |
| documents / `search_documents` | `query: str[1..500]` | `limit: int[1..20]=5`, `after_id: ID|null` | `Page[DocumentHit]` |
| documents / `get_document` | `document_id: ID` | None | `DocumentView` |
| business / `get_order` | `order_id: ID` | None | `OrderView` |
| business / `get_customer` | `customer_id: ID` | None | `CustomerView` |
| business / `list_customer_orders` | `customer_id: ID` | `limit: int[1..50]=20`, `after_id: ID|null` | `Page[OrderView]` |
| tasks / `list_tasks` | None | `customer_id: ID|null`, `status: open|in_progress|resolved|null`, `limit: int[1..50]=20`, `after_id: ID|null` | `Page[TaskView]` |
| tasks / `create_task` | `customer_id: ID`, `title: str[1..200]` | None | `TaskView`, initially open/version 1 |
| tasks / `update_task` | `task_id: ID`, `expected_version: int>=1`, `patch` | None | Updated `TaskView` |

`patch` contains one or both of `title: str[1..200]` and
`status: open|in_progress|resolved`. Explicit nulls, empty patches and unknown
fields fail. No assignment, delete, refund, payment/account mutation, arbitrary
SQL, filesystem or URL-fetch operation is exposed. A page is
`{items: [...], next_after_id: ID|null}`; empty results have an empty list and null
continuation. Search is PostgreSQL English lexical search, not semantic retrieval.
Descriptions and complete input/output JSON Schemas are available through
`tools/list` or `opsdesk-mcp list DOMAIN --full-schema`.

## Authorization and write identity

| Role | Own-tenant reads | Task creates/updates | Reopen resolved task |
| --- | --- | --- | --- |
| viewer | Yes | Denied | Denied |
| support_agent | Yes | Forward transitions and allowed fields | Denied |
| supervisor | Yes | Yes | Yes |

Every call also intersects the persisted scenario's available/permitted tools
and resource ownership. Discoverable does not mean authorized. Cross-tenant and
missing record IDs return the same not-found message. Approval-required writes
fail closed; approval issuance/expiry/verification is not yet implemented.
Forward task transitions are open -> in_progress, open -> resolved, and
in_progress -> resolved. A supervisor may reopen a resolved task. In-progress ->
open remains unsupported even for a supervisor. Same-status/title patches still
form a versioned write under existing service semantics.

Trusted host metadata supplies a signed logical operation ID for writes. The
server maps it to the existing service idempotency key; it cannot be overridden
through arguments. Same identity/arguments returns original recorded task data;
same identity with different arguments gives an idempotency conflict; new intent
requires a new identity. The host must preserve operation IDs across lost-response
retries. See [the signing/retry contract](mcp-integration.md#signed-operation-identity-and-retries).

## Output envelope and provenance

Every known tool returns the following fields in MCP `structuredContent`, with a
matching JSON text content block for compatibility:

```json
{
  "contract_version": "1.0",
  "data": {},
  "error": null,
  "provenance": {
    "source": "opsdesk",
    "domain": "business",
    "tool": "get_order",
    "fixture_id": "opsdesk_baseline",
    "fixture_version": "1.0",
    "seed_hash": "sha256-of-the-registered-seed",
    "trust_classification": "untrusted"
  }
}
```

This block illustrates the envelope shape; the captured tool examples below give
actual `data` objects. Exactly one of data/error is non-null, validated by Pydantic.
Money is an exact decimal string; UTC timestamps use ISO serialization. Documents
and search hits explicitly carry `trust_classification: untrusted`, record ID and
version. Envelope source/domain/fixture/seed metadata provides provenance for
business and document data. Retrieved text is never an instruction or permission.

The adapter bounds argument JSON at 16 KiB and structured payloads at 64 KiB.
Compatibility text, SDK metadata and protocol framing are additional. Oversized
results fail with `response_too_large`; JSON records are never silently truncated.
Search snippets are deliberately bounded excerpts produced by the existing service.

## Stable error semantics

Known-tool failures use MCP `isError=true`, `data=null`, and
`error={code,message,retryable,correlation_id}`. Correlation IDs are generated
32-character hex values. Service error messages are not copied verbatim: only
allowlisted safe text reaches the caller. Output validation failures are internal
errors, distinct from invalid caller arguments.

| Code | Safe message |
| --- | --- |
| `validation_error` | Arguments do not match the tool schema. |
| `not_found` | Record not found. |
| `permission_denied` | Operation is not permitted for this bound actor or context. |
| `approval_required` | This operation requires approval. |
| `version_conflict` | Task version has changed; read the task before a new operation. |
| `idempotency_conflict` | Logical operation was already used for different arguments. |
| `database_unavailable` | The sandbox database operation could not complete. |
| `internal_error` | The tool failed; consult developer logs with the correlation ID. |
| `response_too_large` | Result exceeds the response limit; request a smaller page. |

Only classified storage failures/connection failures carry retryability; the
trusted client never retries automatically. Unknown service codes fail generically.
Unexpected diagnostic details remain in developer logging, never result JSON/text.
Startup errors mask configuration values. Logs are not safe model observations.
An error or lost response is not proof that a write did not commit: reconcile
using the original operation ID rather than issuing a fresh write.

Unknown tool names return SDK-compatible JSON-RPC error `-32602` with safe
`unknown_tool` metadata; malformed protocol/transport errors remain SDK-level
failures. They are not typed results from a known tool.

## Captured synthetic examples for every tool

These input/data pairs were captured from successful stdio MCP calls against the
bundled baseline on Docker PostgreSQL during Checkpoint 2 validation. The envelope
is shared as described above. Created task IDs depend on the trusted host operation
identity; do not treat the example ID as a reusable fixture ID. Optional/default
fields are shown in returned data. These examples are tool checks, not agent or
benchmark results.

### `search_documents`

Input:

```json
{
  "query": "refund eligibility",
  "limit": 1
}
```

Successful `data`:

```json
{
  "items": [
    {
      "document_id": "refund_policy",
      "title": "Refund eligibility policy",
      "snippet": "Synthetic evaluation date: 2026-02-01. A refund review is eligible only when a payment is settled, the order is paid or shipped, the account is active, and the order was created on or after 2026-01-02. Otherwise it is ineligible. Support may create a review task; no refund execution service exists.",
      "version": 1,
      "trust_classification": "untrusted"
    }
  ],
  "next_after_id": null
}
```

### `get_document`

Input:

```json
{
  "document_id": "refund_policy"
}
```

Successful `data`:

```json
{
  "document_id": "refund_policy",
  "title": "Refund eligibility policy",
  "content": "Synthetic evaluation date: 2026-02-01. A refund review is eligible only when a payment is settled, the order is paid or shipped, the account is active, and the order was created on or after 2026-01-02. Otherwise it is ineligible. Support may create a review task; no refund execution service exists.",
  "category": "policy",
  "version": 1,
  "published_at": "2026-01-15T12:00:00Z",
  "trust_classification": "untrusted"
}
```

### `get_order`

Input:

```json
{
  "order_id": "order_001"
}
```

Successful `data`:

```json
{
  "order_id": "order_001",
  "customer_id": "customer_001",
  "status": "shipped",
  "total_amount": "25.00",
  "currency": "USD",
  "version": 1,
  "created_at": "2026-01-20T12:00:00Z",
  "updated_at": "2026-01-20T12:00:00Z"
}
```

### `get_customer`

Input:

```json
{
  "customer_id": "customer_001"
}
```

Successful `data`:

```json
{
  "customer_id": "customer_001",
  "display_name": "Mira Vale (Synthetic)",
  "email": "mira.vale@customers.opsdesk.invalid",
  "version": 1,
  "created_at": "2025-01-01T00:00:00Z"
}
```

### `list_customer_orders`

Input:

```json
{
  "customer_id": "customer_001",
  "limit": 1
}
```

Successful `data`:

```json
{
  "items": [
    {
      "order_id": "order_001",
      "customer_id": "customer_001",
      "status": "shipped",
      "total_amount": "25.00",
      "currency": "USD",
      "version": 1,
      "created_at": "2026-01-20T12:00:00Z",
      "updated_at": "2026-01-20T12:00:00Z"
    }
  ],
  "next_after_id": "order_001"
}
```

### `list_tasks`

Input:

```json
{
  "customer_id": "customer_001",
  "status": "open",
  "limit": 1
}
```

Successful `data`:

```json
{
  "items": [
    {
      "task_id": "task_001",
      "customer_id": "customer_001",
      "title": "Review recent shipment refund",
      "description": "Synthetic support record; review policies before acting.",
      "status": "open",
      "priority": "normal",
      "assigned_actor_id": "support_001",
      "order_id": "order_001",
      "version": 1,
      "created_at": "2026-01-20T12:00:00Z",
      "updated_at": "2026-01-20T12:00:00Z"
    }
  ],
  "next_after_id": null
}
```

### `create_task`

Input:

```json
{
  "customer_id": "customer_001",
  "title": "MCP documentation follow-up"
}
```

Successful `data`:

```json
{
  "task_id": "task_e59a93c4c9343b5db86209c071996ea9",
  "customer_id": "customer_001",
  "title": "MCP documentation follow-up",
  "description": "",
  "status": "open",
  "priority": "normal",
  "assigned_actor_id": null,
  "order_id": null,
  "version": 1,
  "created_at": "2026-02-01T00:00:01Z",
  "updated_at": "2026-02-01T00:00:01Z"
}
```

### `update_task`

Input:

```json
{
  "task_id": "task_e59a93c4c9343b5db86209c071996ea9",
  "expected_version": 1,
  "patch": {
    "status": "resolved"
  }
}
```

Successful `data`:

```json
{
  "task_id": "task_e59a93c4c9343b5db86209c071996ea9",
  "customer_id": "customer_001",
  "title": "MCP documentation follow-up",
  "description": "",
  "status": "resolved",
  "priority": "normal",
  "assigned_actor_id": null,
  "order_id": null,
  "version": 2,
  "created_at": "2026-02-01T00:00:01Z",
  "updated_at": "2026-02-01T00:00:02Z"
}
```
