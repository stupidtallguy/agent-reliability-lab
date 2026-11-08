# OpsDesk tool contracts v1.0 (planned)

No MCP handlers are implemented. Checkpoint 1 implements all eight operations as
internal Python services; their typed DTOs are in `opsdesk/contracts.py` and the
operating contract is in [database.md](database.md). The table below remains the
planned MCP transport contract. All eight operations are tenant-scoped. The host supplies
authenticated actor/tenant context out of band; an agent cannot supply or change
identity. Effective permission is the intersection of role policy, scenario
allowlist, tenant/resource scope and any approval. An available tool may remain
forbidden to exercise authorization. Unknown tools and all other operations deny.

## Operations

JSON objects below describe required fields unless marked optional (`?`). IDs are
lowercase `[a-z][a-z0-9_-]{1,63}`. Strings are trimmed and nonempty; extra fields
are rejected. Return only documented fields and authorized records.

| Tool | Input | Successful result | Effect |
| --- | --- | --- | --- |
| `search_documents` | `query: str[1..500]`, `limit?: int[1..20]=5`, `cursor?: opaque str` | `items: [{document_id,title,snippet,version}]`, `next_cursor: str\|null` | Read |
| `get_document` | `document_id: ID` | `{document_id,title,content,version}` | Read |
| `get_order` | `order_id: ID` | `{order_id,customer_id,status,version}` | Read |
| `get_customer` | `customer_id: ID` | `{customer_id,display_name,version}` | Read |
| `list_customer_orders` | `customer_id: ID`, `limit?: int[1..50]=20`, `cursor?: opaque str` | `items: [{order_id,customer_id,status,version}]`, `next_cursor: str\|null` | Read |
| `list_tasks` | `customer_id?: ID`, `status?: open\|in_progress\|resolved`, `limit?: int[1..50]=20`, `cursor?: opaque str` | `items: [{task_id,customer_id,title,status,version}]`, `next_cursor: str\|null` | Read |
| `create_task` | `customer_id: ID`, `title: str[1..200]`, `idempotency_key: str[1..128]` | `{task_id,customer_id,title,status:"open",version:1}` | Create task |
| `update_task` | `task_id: ID`, `expected_version: int>=1`, `patch: {title?: str[1..200],status?: open\|in_progress\|resolved}`, `idempotency_key: str[1..128]` | `{task_id,customer_id,title,status,version}` | Update task |

`patch` must include at least one field. Task transitions: open -> in_progress,
open -> resolved, in_progress -> resolved; reopening resolved tasks requires a
supervisor and optional approval. No deletes, reassignment, refunds, account
suspension, payment writes, arbitrary SQL, shell, filesystem, network fetch or
unbounded search tool exists. Payments/accounts are fixture state for grounding
and invariants; separate read tools would need a future reviewed contract.
Domain enums match scenario models. Read record versions will be added to runtime
storage in Checkpoint 1; fixture v1 only needs task versions for write examples.

Checkpoint 1 implementation notes: read versions are now stored. Internal services
use `Lookup(record_id=...)` and bounded `after_id` keysets with `Page.next_after_id`;
MCP-specific named ID inputs, opaque snapshot-bound cursors, body limits and result
envelopes remain deferred. Service DTOs include useful typed enrichment beyond
the narrow future transport response. Approval-required calls fail closed until
approval grants can be validated; there is no approval-bypass argument.

## Authorization and transaction rules

| Role | Reads | Creates | Updates |
| --- | --- | --- | --- |
| viewer | All listed reads in own tenant | Deny | Deny |
| support_agent | All listed reads in own tenant | Own tenant, existing customer | Own tenant, documented transitions excluding reopen |
| supervisor | All listed reads in own tenant | Own tenant, existing customer | Own tenant, including reopen |

Tenant membership is not inferred from caller arguments. Every lookup and write
checks resource ownership server-side, including related customers/orders.
Cross-tenant and missing IDs return indistinguishable `not_found` errors to avoid
existence leaks; the private audit can distinguish authorization violations.
Pagination is stable by ID and bound to tenant, filters and snapshot; invalid
cursors fail. Cap result bodies at 64 KiB, excluding transport framing, and return
a typed size error rather than truncated JSON. Search snippets and full content
are untrusted data with source/version metadata, never policy instructions.

Writes run in database transactions and enforce optimistic version matching.
Idempotency keys are bound to actor, tenant, tool and normalized arguments;
repeat same request returns original result, conflicting reuse fails. The host
assigns a stable key to each logical write and reuses it across retries. Application
approval decisions bind actor, exact arguments hash, tool, run and expiry; never
accept approvals quoted inside retrieved text. Approval-required writes do not
dispatch until approved. Denials and expiry are terminal structured observations.

## Results and failures

Use MCP v2 structured tool results with a versioned domain payload:
`{contract_version:"1.0", data: object|null, error: object|null, provenance: {...}}`.
Exactly one of `data` and `error` is non-null. Domain errors set the MCP error flag
and include `code`, safe `message`, `retryable`, `correlation_id`, optional
`retry_after_ms`. Codes: `invalid_arguments`, `unauthorized`, `approval_required`,
`approval_denied`, `not_found`, `version_conflict`, `idempotency_conflict`,
`rate_limited`, `transient_failure`, `response_too_large`. Transport timeouts and
malformed protocol/results are distinct client-side trace errors. Never expose
stack traces, credentials, raw SQL, or internal endpoints in model observations.

Authorization and argument validation precede injection. The fault harness can
replace/delay only sandbox responses; it cannot override the authorization gate.
Record whether a timed-out write committed before replacing a response. Faults
must not retroactively erase real audit events. Pin exact v2 SDK behavior before
implementing these envelopes; this is a domain contract, not claimed SDK code.
