# Final integration preparation

Reviewed on November 21, 2026, from CP19 `adfbb47b35ad3e8a8ddb7a5bd66690bdf0179c74`. Main is `cf78bd5e28bc9520f51ecdf6f2755055d68b85e3`. PR #3 is merged and PRs #4–#9 remain open drafts. This preparation adds a dashboard connection correction.

| PR | Reviewed head | Proposed integrated tree |
| --- | --- | --- |
| #4 | `2f0cc1594768851214adca0b29317337672414cb` | `03fb4062df8d7f393dc441fa153080ae4def2180` |
| #5 | `acde24976f8e95121af23cec42fece7453303072` | `044806442a3aaa4e25b3f5949280b5dc84ca58f9` |
| #6 | `66d6cce255be3a216cbac184639f162838f4428d` | `108004589852794f7142b2ee3bef496665acabb9` |
| #7 | `5abd4c3e05002665e77ce00fc8b368482c9c3b70` | `fa94d9be8385d4d85cc75e4d3eacd7171e56dd65` |
| #8 | `022bb3e27123cfb7d703c910df0ac30d0746db66` | `52de311941f4e2dc47c00cbbfa9163f059810f2e` |
| #9 | `adfbb47b35ad3e8a8ddb7a5bd66690bdf0179c74` | `c8ec099553ebe276634fed7a2ea7ccc944e143b8` |

The rehearsal uses a temporary shared clone and creates merge commits only in that clone. Each predecessor is an ancestor of its successor. Each original stacked patch equals the proposed patch byte for byte, and the evolving merge tree equals that successor's reviewed tree. An owner may approve retargeting #4 to main, verify its diff and fresh integration CI, merge it with a merge commit, then repeat for #5 through #9 and the timezone correction. Preserve all feature refs until descendants are integrated. Recompute fingerprints if any input changes. Existing stacked CI is evidence for the reviewed base and head. Retargeting requires validation of the updated merge ref. See the exact commands and reviewed CI run IDs in [the integration runbook](checkpoint-19-groq-activation-gate.md).

## Timezone defect and resolution

The writer creates UTC journal timestamp strings. The dashboard read connection previously inherited the PostgreSQL timezone. In Asia/Tehran, Psycopg returned the same instant with an offset, and the signed-evidence comparison serialized it differently. This produced a false journal inconsistency before the actual mutated attempt could be reported. The original assertion was reproduced on a disposable PostgreSQL 18 cluster. The server default was changed between UTC and Asia/Tehran only on the disposable database.

The minimal correction pins dashboard sessions to UTC, matching the existing writer connection contract. No historical seal, signature, score or report bytes are changed. The existing adversarial dashboard test retains all assertions, adds two requested timezone cases and checks actual read-only and UTC connection settings. Its Streamlit completion timeout is 30 seconds to allow cold startup. After the correction, both parameter cases pass under both server defaults. UTC is enforced by the application connection, so operators need no server-wide timezone change.

## Security and acceptance evidence

The source keeps Groq and paid OpenAI network gates false. Qualification requires separate account evidence, credential commitment, authorization, a single-use permit and its own ledger. The study pins qualification evidence and cannot use a mock qualification for live access. Minute/day capacity, cross-ledger quotas, revocation after pacing and 429 behavior remain covered by the PostgreSQL and HTTP mock suites. Development-only execution, score pinning and historical signed-report checks remain in the full matrix.

The correction changes the dashboard read connection, its regression and this report. Original task transactions, historical evaluators, benchmark fixtures, Ed25519 algorithms and frozen reports are preserved. The original tag object is `0a00726f11e9b3ebc5904bdbfe1f046d3627d730`, pointing to release commit `f2fbfa75e8bb990671fa692998c5585c2cd5ebe4`.

Full Windows and hosted Linux Python 3.11/3.12 results and exact correction SHA are recorded in the delivery report and corrective draft PR. Pattern scans of the complete proposed tracked tree and sealed-data Git guard are engineering checks. They cannot establish absence of past exposure or verify private account eligibility. The protected database is neither queried nor modified. Qualification and provider inference remain behind owner approval.
