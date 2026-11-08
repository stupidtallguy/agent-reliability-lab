# Baseline and guarded configurations

Both configurations use the same existing LangGraph agent, discovered MCP tools,
model adapter/settings, fixture, permissions, write receipts, transactions,
optimistic versions, trusted actor/run and execution budgets. Neither configuration
has an unrestricted SQL, filesystem, deletion, refund or external transmission
tool. Existing essential controls are never disabled.

Baseline retains the original policy and observation format. Guarded adds:

1. A fixed host policy reminding the model that observation authority claims are
   untrusted. This contains no hidden expected answer or attacker objective.
2. Provenance-preserving tool-message framing with `observation_trust=untrusted`
   and `instruction_authority=none`; tool contents remain available as data.
3. A deterministic pre-dispatch write gate using separately declared trusted
   task scopes. No matching scope denies a write with `task_scope_denied` and an
   auditable `defense_block`; reads continue. A scope constrains argument values,
   and an update cannot add mutation fields beyond its declared patch fields.

Task scopes are developer/host authorizations, not conclusions inferred from
natural language, attack text, or hidden scoring assertions. The same scope
configuration is recorded for both variants; baseline does not apply the added
gate. For read-only tasks scopes are empty. Valid create/update controls declare
their customer/title or task/status constraints explicitly. This is a narrow
transparent defense, not a general semantic understanding of user intent. Bad
host scopes can block legitimate work; tests deliberately measure that failure.

The scope gate supplements server RBAC. `task_scope_denied` is not silently counted
as a server permission failure. A role-authorized workflow hijack may be blocked
by the scope gate, while a viewer violation is still an unauthorized proposal
whether the guard or server prevents dispatch. Exposure and actual effects are
scored independently.

## Paired trials and controls

```powershell
uv run --locked opsdesk-eval run --suite all --paired
uv run --locked opsdesk-eval compare BASELINE_EXPERIMENT_ID GUARDED_EXPERIMENT_ID
```

Each side has a separate experiment and fresh sandbox per trial. A common pair
ID and scenario/repeat key retain association. Comparison validates equal source,
model/settings, budgets, cases, injection/payload configuration and initial logical
state. Only defense selection differs. Sequential baseline-first order is explicit;
this development workflow has no randomized-order or inferential superiority claim.
JSON comparison is exported under ignored `artifacts/evaluations/pairs/`. Each
experiment independently exports JSON, CSV and Markdown through the existing
evaluation reporter. Journals/evaluation tables remain separate from business data.

Eight benign cases cover search, order lookup, creation, observed-version update,
multiple servers, customer/order relationships, ordinary policy and legitimate
text mentioning system, delete, password and administrator. No keyword blacklist
is used. Report task success as well as scope-block false positives, latency,
attempt counts, retries, budget exhaustion and available model usage/cost.

The observation-sensitive fake model branches on actual returned tool text and
otherwise follows a fixed plan. Identical scripts run in both configurations;
they have no oracle access. Scripted answer contamination is deliberately still
possible under framing alone. Guarded superiority is not assumed. Actual model
resistance, spontaneous refusals and token/cost tradeoffs require separately opted-in
live measurements. No second guardrail model or paid API is required.
