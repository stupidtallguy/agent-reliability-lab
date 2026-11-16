# Checkpoint 18 — Free-tier provider feasibility

CP18 qualifies direct Groq on-demand Chat Completions with `openai/gpt-oss-20b` for an exploratory development pilot on an owner-verified Free organization. The delivered build keeps external Groq inference disabled. Scripted replies exercise the HTTP request, parser, PostgreSQL budget, MCP, scoring and report paths with no provider credentials. The discovery catalog was used to identify leads. Qualification is based on provider documentation. [Discovery catalog](https://github.com/OuterSpacee/free-ai-apis)

## Official provider comparison

Documentation checked November 16, 2026. Account eligibility, route availability and usage limits require a fresh check before activation.

| Criterion | Groq direct | OpenRouter |
| --- | --- | --- |
| Free eligibility and credential | Groq lists the model on the Free plan. Use a key issued in an owner-controlled Free organization. Developer billing requires an upgrade and a payment method. [Rate limits](https://console.groq.com/docs/rate-limits), [billing](https://console.groq.com/docs/billing-faqs), [authentication](https://console.groq.com/docs/quickstart) | The exact comparison variant is `openai/gpt-oss-20b:free`. OpenRouter documents zero model prices and no purchase requirement for `:free` variants. The account key works with both free and paid models. [Variant](https://openrouter.ai/openai/gpt-oss-20b%3Afree/providers), [Free models](https://openrouter.ai/collections/free-models) |
| Chat and tools | `POST https://api.groq.com/openai/v1/chat/completions`. Text messages, client-side function tools, JSON argument strings and `tool_call_id` for tool responses. The candidate supports local function calling. CP18 disables parallel tool calls and provider-hosted tools. [API reference](https://console.groq.com/docs/api-reference), [local tools](https://console.groq.com/docs/tool-use/local-tool-calling), [model card](https://console.groq.com/docs/model/openai/gpt-oss-20b) | `POST https://openrouter.ai/api/v1/chat/completions` exposes the same general function schema. The selected underlying endpoint must support the specific parameters and tool response behavior. [Client tools](https://openrouter.ai/docs/guides/features/tool-calling), [routing](https://openrouter.ai/docs/guides/routing/provider-selection) |
| Model identity and token limits | `openai/gpt-oss-20b` identifies the model by slug. The slug has no immutable deployment version. CP18 checks the returned model and a preregistered `system_fingerprint` on every successful response. Published limits are 131,072 context and 65,536 maximum output tokens. The pilot uses smaller limits. [Model card](https://console.groq.com/docs/model/openai/gpt-oss-20b), [API reference](https://console.groq.com/docs/api-reference) | The free variant documents a 131,072-token context. A fixed free endpoint with a verified output ceiling, stable backend identity and the necessary tool capability was not established for this comparison. [Variant](https://openrouter.ai/openai/gpt-oss-20b%3Afree/providers), [routing](https://openrouter.ai/docs/guides/routing/provider-selection) |
| Provider limits | The model's Free-plan reference limits are 30 requests/minute, 1,000 requests/day, 8,000 tokens/minute and 200,000 tokens/day. Organization settings give actual limits and may differ. [Rate limits](https://console.groq.com/docs/rate-limits) | Unfunded `:free` access is 20 requests/minute and 50 requests/day. Failed attempts count. Upstream providers can impose additional limits. [Free models](https://openrouter.ai/collections/free-models), [rate limits](https://openrouter.ai/docs/api/reference/limits) |
| Usage and request attribution | Chat Completions can return `x_groq.id`, the backend fingerprint and prompt, completion and total token counts. Latency is measured locally. Token counts and local pricing do not establish invoice charges. [API reference](https://console.groq.com/docs/api-reference) | Usage accounting provides token counts, a generation ID and cost information. The generation record still needs a pinned serving route for experimental attribution. [Usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting) |
| Retention | Groq does not retain inference content by default. Reliability and abuse exceptions can retain it for up to 30 days, subject to legal exceptions. The organization can configure zero data retention. [Data controls](https://console.groq.com/docs/your-data) | OpenRouter logging settings and the serving provider's retention policy both apply. OpenRouter supports a ZDR routing constraint. Eligibility of a specific free route must be checked. [Data collection](https://openrouter.ai/docs/guides/privacy/data-collection), [provider logging](https://openrouter.ai/docs/guides/privacy/provider-logging) |
| Routing, retries and billing | CP18 sends the exact model to Groq with `service_tier=on_demand`. The adapter uses direct HTTP with retries disabled, redirects disallowed and no model fallback. Groq's `auto` tier can fall back to Flex and is forbidden. On-demand is billable on a paid organization. Free eligibility depends on the organization behind the credential. [Service tiers](https://console.groq.com/docs/service-tiers), [auto fallback](https://console.groq.com/docs/production-readiness/optimizing-latency), [billing](https://console.groq.com/docs/billing-faqs) | Routing supports provider allowlists, disabled fallback, required parameter support and price filters. The generic free router can select different models. A single HTTP request can otherwise involve upstream fallback independently of client retries. CP18 does not adopt this provider. [Provider selection](https://openrouter.ai/docs/guides/routing/provider-selection), [model fallbacks](https://openrouter.ai/docs/guides/routing/model-fallbacks) |

## Implementation and evidence

- The frozen Groq profile pins the direct endpoint, exact model, on-demand tier, medium reasoning effort, no reasoning disclosure and the expected backend fingerprint. OpenAI remains on its existing SDK path. The Groq adapter reuses the single-use HTTP permit, sealed model request, Chat Completions parser, LangGraph agent and MCP runtime.
- The existing broker admits at most 16 Groq calls per pilot and zero provider retries. A separate rolling 24-hour ceiling of 16 permits across Groq ledgers in the same database is serialized by a transaction-scoped PostgreSQL lock. Mock runs use separate quota pools by research scope. A consumed permit counts even when the request times out or its response is lost.
- The broker reserves tokens and freezes the affected ledger on unexpected model, backend fingerprint, routing or metering evidence. Ambiguous failures and missing usage keep their reservation. The zero-dollar manifest is an admission assumption bound to the Free plan. Provider-reported token counts, provider-reported charges and an independently verified invoice are distinct evidence. Reports identify unavailable charges and unverified invoices.
- The production-shaped pathway rejects missing or revoked authorization, altered wire requests and reused permits before transport. The repository's `GROQ_FREE_NETWORK_ENABLED` is false and separate from the paid OpenAI fuse. API keys, CLI choices and test authorizations cannot open the disabled route.
- The exploratory design uses the existing `multi_step_resolve_task` development scenario, two pairs in opposite arm orders and four isolated MCP sandboxes. The two arms share provider, model and ceilings. The guarded arm changes the scope and observation framing. Success comes from score-pinned tool evidence. These four trials test feasibility on one template.

## Safe reproduction

Run PowerShell from the workspace. Use a disposable database and leave the provider credentials unset. Confirm port 55436 is available before starting the dedicated Compose project.

```powershell
docker compose -p opsdesk-cp18-local -f compose.test.yaml up -d --wait
$env:OPSDESK_DATABASE_URL = 'postgresql+psycopg://opsdesk_ci@127.0.0.1:55436/opsdesk_lab_ci'
$env:OPSDESK_ALLOW_SANDBOX = '1'
$env:OPSDESK_TEST_OWNED = '1'
Remove-Item Env:GROQ_API_KEY, Env:OPENROUTER_API_KEY, Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
uv sync --locked --extra stack
uv run --locked pytest -q tests/test_cp18_groq.py tests/integration/test_cp18_groq.py
uv run --locked pytest -q -m 'not integration'
uv run --locked pytest -q -m integration
uv run --locked opsdesk-research benchmark-guard
docker compose -p opsdesk-cp18-local -f compose.test.yaml down
```

Given a registered CP12 development protocol reference, these commands only create local drafts or read frozen data. Use a `provider: groq` profile with `input_ceiling`, `output_ceiling` and a fixture `expected_system_fingerprint` for mock preparation. The pricing manifest uses currency USD, the exact model and an explicit effective window and provenance. In this mock preparation the input, cached input, output and fixed request rates are zero. Follow the [registration commands](checkpoint-16-real-model-readiness.md) for the protocol and plan. Treat generated drafts as inputs for review.

```powershell
uv run --locked opsdesk-research --scope cp18 benchmark-live-draft parent-ref.json cp18-draft --profile groq-profile.json --pricing zero-pricing.json --maximum-usd 0 --identity cp18_development
uv run --locked opsdesk-research --scope cp18 benchmark-live-preflight plan-ref.json --authorization authorization-ref.json
uv run --locked opsdesk-research --scope cp18 benchmark-pilot-verify report-ref.json --output cp18-exports
```

## Operator authorization worksheet

Complete privately before requesting a separate activation review. A fully filled worksheet is an input to review and does not activate any network.

| Record | Required operator evidence |
| --- | --- |
| Plan and scope | Pin the verified source SHA, dependency fingerprint, development protocol, allocation/schedule, evaluator, pilot plan, ledger and authorization references. No held-out or customer data. |
| Provider and key ownership | Verify in the Groq Console that the dedicated organization remains on Free, has no billing payment method, paid route, recharge or concurrent trial traffic, and that the operator-created key belongs to that organization. Save redacted evidence privately and pin its SHA-256 in `free_organization_evidence`. Compute `free_key_commitment` locally with `groq_key_commitment` from the exact credential. The permit checks that commitment before dispatch and reports omit it. A rotated key requires a new authorization. Read the credential via the secret store or environment and keep it out of command arguments, artifacts and logs. |
| Route and backend | Exact endpoint and model shown above. Freeze a backend fingerprint established by provider evidence or a separately authorized, accounted qualification call. Never use the fixture fingerprint for a real run. A fingerprint can detect drift and gives no guarantee of repeatability or stable model weights. |
| Limits | Authorize at most 16 calls per run and per database over a rolling 24h, four calls per trial, zero model retries and a run of at most 15 minutes. Choose measured request and output ceilings within the published context. A 6,000 input/1,024 output planning ceiling would reserve up to 112,384 tokens across 16 calls. Check measured prompt size and organization tokens/minute before approving any pacing or limits. The adapter sends no request to look up this quota. |
| Financial and data conditions | Pin a current zero-cost Free-plan manifest. Confirm the organization's actual quotas and retention controls. Reject paid activation, external fallback, and auto-purchase. Review provider usage and billing after the run. Groq's response does not attest to the plan or invoice and the local zero-dollar ceiling cannot protect a misconfigured paid account. |
| Scope of approval and stop conditions | Record operator, reviewed deployment, bounded authorization window and revocation procedure. Stop on rate limiting, unavailable entitlement, backend drift or unsupported billing evidence. Missing response or usage retains exposure in the ledger. No retries without a separate change to the experimental plan. |

External activation remains disabled. A later run needs an explicitly reviewed deployment, a registered `groq_free` authorization and an intentional `--activate-free` command. Mock validation establishes pipeline behavior only. No real requests, charges, invoice, account entitlement or model outcomes were observed by CP18.
