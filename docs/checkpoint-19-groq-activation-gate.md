# Checkpoint 19 — Release integration and Groq qualification

This package prepares the one-request qualification and the separate four-trial development pilot. Both external provider gates remain closed in this branch. CP19 exercised scripted HTTP replies, a real disposable PostgreSQL ledger, the existing MCP sandboxes, and evaluator 1.7.0. Account entitlement, a real provider fingerprint, provider charges and model-generated outcomes remain unverified.

## Integrating the stack

Main at review was `cf78bd5e28bc9520f51ecdf6f2755055d68b85e3`, the two-parent merge of PR #3. Its tree equals `880ad58d4251316d7dc11ccb29f79d1302fc4b15`. The `v1.0.0` tag object remains `0a00726f11e9b3ebc5904bdbfe1f046d3627d730` and peels to `f2fbfa75e8bb990671fa692998c5585c2cd5ebe4`. The evaluator and Ed25519 publication implementation are outside the CP19 diff.

| PR | Reviewed head | Current base | Exact-head CI | Intended files |
| --- | --- | --- | --- | ---: |
| #3 | `880ad58d4251316d7dc11ccb29f79d1302fc4b15` | main, merged | [43736320493](https://github.com/stupidtallguy/agent-reliability-lab/actions/runs/43736320493) | — |
| #4 | `2f0cc1594768851214adca0b29317337672414cb` | CP12 | [43745414883](https://github.com/stupidtallguy/agent-reliability-lab/actions/runs/43745414883) | 17 |
| #5 | `acde24976f8e95121af23cec42fece7453303072` | CP13 | [43758097249](https://github.com/stupidtallguy/agent-reliability-lab/actions/runs/43758097249) | 19 |
| #6 | `66d6cce255be3a216cbac184639f162838f4428d` | CP14 | [43763951909](https://github.com/stupidtallguy/agent-reliability-lab/actions/runs/43763951909) | 17 |
| #7 | `5abd4c3e05002665e77ce00fc8b368482c9c3b70` | CP15 | [43820355255](https://github.com/stupidtallguy/agent-reliability-lab/actions/runs/43820355255) | 18 |
| #8 | `022bb3e27123cfb7d703c910df0ac30d0746db66` | CP16 | [43831758608](https://github.com/stupidtallguy/agent-reliability-lab/actions/runs/43831758608) | 17 |

Owner sequence is #4 → #5 → #6 → #7 → #8 → CP19. For each row, wait until the reviewed predecessor is an ancestor of current main. Compare the exact original PR patch against the proposed patch, and compute the merged tree locally. At review every adjacent merge base was the predecessor shown above, and every deferred merge into the reviewed main produced the corresponding head tree. A change in main requires repeating the checks.

```powershell
git fetch --no-tags origin main
# Fill these from the reviewed row and its predecessor before each retarget.
git merge-base --is-ancestor $previousReviewedHead origin/main
git merge-base origin/main $reviewedHead
git diff --binary --output=expected.patch $previousReviewedHead $reviewedHead
git diff --binary --output=proposed.patch origin/main...$reviewedHead
Get-FileHash expected.patch, proposed.patch
git merge-tree --write-tree origin/main $reviewedHead
git rev-parse "$reviewedHead^{tree}"
```

The merge base should equal the predecessor and the patch hashes should match. Review any differing merged tree before proceeding. Retarget only that PR to `main`, confirm the GitHub diff and head again, and require fresh 3.11/3.12 CI on its proposed main integration. Existing stacked CI verifies the prior base. If retargeting does not start CI, run the matrix explicitly against the proposed merge before approving it. Merge using a merge commit to retain the reviewed heads as ancestors. Verify the new main tree, the reviewed head as an ancestor and post-merge CI before moving on. Keep the feature refs until descendants have been integrated.

## Account and route review

Use the [operator worksheet](cp19-groq-operator-worksheet.json) privately. Require recent redacted Groq Console evidence for ownership, Free status, absence of payment method, recharge and paid subscription, identity of the account-issued key, model permission, quotas, absence of competing traffic, and suitable data retention. Hash that evidence for the profile. Compute `groq_key_commitment` from the local secret-store injection, with no key echoed or written to files. A zero-dollar local price is an admission assumption. Recheck actual usage and billing after any authorized run. [Groq billing](https://console.groq.com/docs/billing-faqs) · [Groq data controls](https://console.groq.com/docs/your-data)

Groq lists `openai/gpt-oss-20b` in the Free table at 30 RPM, 1,000 RPD, 8,000 TPM and 200,000 TPD. Organization-specific rates can differ. Groq can set separate ITPM/OTPM limits, visible in the account’s Limits view, without publishing a fixed pair for this account. The `x-ratelimit-{limit,remaining,reset}-requests` family refers to **daily** requests and the corresponding `-tokens` family refers to **minute** tokens. `retry-after` is reported in seconds on HTTP 429. Headers are preserved as advisory evidence and never trigger a resend. The exact route is direct on-demand Chat Completions, with a returned model identity and a system fingerprint representing backend configuration. [Groq rate limits](https://console.groq.com/docs/rate-limits) · [Groq API reference](https://console.groq.com/docs/api-reference) · [Groq model](https://console.groq.com/docs/model/openai/gpt-oss-20b)

A transaction-scoped lock serializes the database-local rolling quota across all live Groq ledgers. The transaction uses READ COMMITTED before reading any rows. Each committed dispatch counts, including qualification and unknown responses. Mock quotas are isolated by research scope and from the real quota. CP19 additionally reserves tokens against the reviewed minute/day ceilings and any split minute ceilings. Before HTTP it waits outside the transaction, then reacquires locks and rechecks authorization, deadline and capacity. HTTP 429 records the status and freezes further dispatch in that ledger. Other traffic in the organization is outside the database's visibility.

## Qualification and experiment procedure

1. Identify the owner-reviewed build, exact commit and lock fingerprint. Prepare a fresh, dedicated local test-owned PostgreSQL database for synthetic data and one private research scope used throughout both phases. Review the worksheet and separately authorize the one-request qualification only. The commands below require the reviewed owner activation environment before they can send HTTP.
2. Create a Groq profile with 256 input and 256 output tokens, current account pacing, Free-organization evidence and a credential commitment. Leave the expected fingerprint and qualification references null or absent. Use the contemporaneous zero-price manifest and the existing development parent. Draft and append the resulting protocol and plan, then draft and append the separately approved authorization. Use its returned reference.
3. Run preflight first. Qualification sends only `Reply with OK.` with no tools. The single-use permit is committed before the request. Use the evidence command to reconstruct the request, provider model, fingerprint, usage, rate-limit fields, dispatch time and event hash. Missing usage retains the reservation and cannot produce an eligible pin. An absent/changed identity, 429, timeout or refusal to grant capacity requires operator investigation. Recover evidence read-only after interruption. A consumed permit is never resent.
4. Prepare a **new** Groq study profile, with the exact fingerprint, qualification authorization reference and event hash, same account evidence, credential commitment and limit evidence. A real profile rejects evidence from a mock authorization. Use the frozen plan in the worksheet, with one existing development scenario `multi_step_resolve_task`, two opposite arm orders, four isolated trials, matching model and evaluator 1.7.0. The mock demonstrated the draft ceiling of 7,700 input + 256 output per request. This ceiling requires the operator’s limits to support it. Lower actual limits or longer tool responses can lead to incomplete trials. The supplied recommendation budgets up to 127,296 reserved tokens across 16 calls, zero provider retries, 1,200 seconds for the paced plan and a 120-second turn deadline including wait.
5. Give the study a distinct protocol, plan, authorization and ledger. Wait until the qualification dispatch falls out of the rolling 24-hour window if the study needs all 16 permits. Verify other holds have also expired. Record the new source, protocol, schedule, price, authorization and evaluator references. A separate explicit operator decision authorizes the study. Stop on evidence/account drift, an expired or revoked approval, a 429, a model/fingerprint or pricing mismatch, or unsupported input. An incomplete or interrupted run is retained as such. Regenerate the report using the stored references, and inspect the account invoice separately.

For future owner use, the following commands stage private files. Use one `Scope` throughout. `parent-ref.json` is the reference to the registered CP12 development parent. Capture each successful `append` response as a reference for the next command. Set `Deadline` to a reviewed UTC timestamp in each phase. CLI draft and preflight work with external access disabled. The two execution commands stay behind the separately reviewed deployment gate.

```powershell
uv run --locked opsdesk-research --scope $Scope benchmark-live-draft parent-ref.json qualification-draft --profile qualification-profile.json --pricing zero-price.json --maximum-usd 0 --identity cp19_qualification --qualification
uv run --locked opsdesk-research --scope $Scope append qualification-draft/protocol.json
uv run --locked opsdesk-research --scope $Scope append qualification-draft/plan.json
uv run --locked opsdesk-research --scope $Scope benchmark-live-authorize-draft qualification-plan-ref.json --profile qualification-profile.json --mode groq_free --deadline $Deadline
uv run --locked opsdesk-research --scope $Scope append qualification-authorization.json
uv run --locked opsdesk-research --scope $Scope benchmark-live-preflight qualification-plan-ref.json --authorization qualification-auth-ref.json
# Only after separate owner authorization and reviewed activation
uv run --locked opsdesk-research --scope $Scope benchmark-live-qualify qualification-auth-ref.json --activate-free
uv run --locked opsdesk-research --scope $Scope benchmark-live-qualification-evidence qualification-auth-ref.json

uv run --locked opsdesk-research --scope $Scope benchmark-live-draft parent-ref.json study-draft --profile study-profile.json --pricing zero-price.json --maximum-usd 0 --identity cp19_study
# Append study protocol, plan and distinct authorization using the same workflow.
uv run --locked opsdesk-research --scope $Scope benchmark-live-preflight study-plan-ref.json --authorization study-auth-ref.json
# Only after separate study authorization
uv run --locked opsdesk-research --scope $Scope benchmark-live-run study-auth-ref.json --activate-free
uv run --locked opsdesk-research --scope $Scope benchmark-pilot-verify report-ref.json --output verified-report
```

Safe validation uses the disposable database workflow described in [CP18](checkpoint-18-free-tier-portability.md). With provider credentials unset, run `uv run --locked pytest -q tests/integration/test_cp18_groq.py tests/test_cp18_groq.py`. The tests simulate time and replace transport before exercising any dormant live-only logic.

This is exploratory feasibility over a single template. Pairing controls selected conditions, and the independent oracle measures task evidence. A fingerprint can detect reported serving drift without guaranteeing deterministic outputs. Mock observations demonstrate engineering behavior. They do not establish production reliability, model effectiveness, an actual Free entitlement or an independently verified invoice.
