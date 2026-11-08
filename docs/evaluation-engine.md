# Objective evaluation engine (Checkpoint 4, version 0.5.0)

The evaluator is independent of the agent's prompt, model declaration and terminal
status. It uses frozen scenario requirements, consistent pre/post snapshots,
durable proposals/attempts, MCP outcomes, receipts, mutation audits and the final
response. No LLM judge, attack runtime, dashboard or provider comparison is used.

## Pipeline and storage

`load/validate -> fresh registered sandbox -> verify fixture -> discover contracts
-> execute existing agent -> exclusive evidence snapshot -> reconcile -> score
-> append result -> report -> owned cleanup`.

The runner is serial within one experiment; independent experiments can run
concurrently. Each repeat gets unique experiment/trial/execution/sandbox identities
and its own schema. It never reuses a mutated sandbox. The six original JSON files,
their scenario models and their inline fixture hashes are unchanged.

Alembic creates `opsdesk_evaluation` separately from business and agent schemas:

| Table | Purpose |
| --- | --- |
| experiments | Immutable versioned manifest/configuration and content hash |
| trials | Scenario/actor/config references, repeat pairing, lifecycle, frozen evidence, ownership and cleanup |
| scores | Append-only scoring revisions, full oracle specification/hash, evaluator version/source hash, findings and metrics inputs |
| reports | Frozen aggregate metrics and the exact scoring IDs selected |

`trial_id` identifies an execution trial; `scoring_id` identifies a unique evaluation
revision. `execution_id` is null for cases never started, rather than inventing an
agent execution. Trial lifecycle/cleanup metadata is explicitly mutable; frozen
evidence, score revisions and manifests are not overwritten by the API. Primary/
foreign keys and per-trial locking protect concurrent score revision allocation.
This is application immutability, not a tamper-proof log against the database owner.

Manifests include scenario hashes, configuration ID, provider/exact model,
supported model settings, repeats, budgets, SDK versions, source SHA, source/lock
hashes and platform. A dirty checkout is recorded; outside Git its dirty state is
unknown. A source SHA is required: supply `--source-commit` when running an
installed wheel outside a checkout; its dirty state remains unknown. Repeats
preserve scenario/trial-index pairing for future comparisons.

## Contracts and oracles

Plain `Scenario` v1 files remain authoritative. Optional `Case` wrappers contain
`scenario` and `oracle`; the latter is an `OracleSpec` v1 sidecar. An experiment's
`annotations` map can supply sidecars keyed by scenario ID. `scenario_hash`, when
present, must match. The checked-in development configuration pins these hashes.

Legacy predicates retain their documented meanings:

- RFC 6901 final-state pointers; missing differs from null; structural equality
  is type-sensitive, including boolean versus integer.
- NFC, case-sensitive literal response substring checks; missing final responses
  fail both contains and not-contains. No exact full-answer equality is required.
- Inclusive trace count bounds, authorization filters and optional execution filter.
- All required final-state predicates and mutation constraints, plus any complete
  success path. Alternate paths are not a single reference sequence.

Sidecars add required mutation counts with before/after field selectors, bounded
response fact/refusal groups, extra forbidden changes and tool-admissibility rules.
They cannot weaken the legacy required state or forbidden/unlisted-change rules.
Response groups use case-folded NFC literal phrases, normalized whitespace and
word boundaries; each group allows synonyms. They remain limited deterministic
checks, not general semantic understanding or proof against negation/quoting.
Scenario authors must review factual sufficiency and add negative facts as needed.

The v1 state projection deliberately excludes enrichment/simulation timestamps.
It is used for existing field-level mutation rules. Full logical snapshots and an
audit-chain reconstruction independently detect unexplained changes to enriched
fields, actors, tenants and other records. Such contradictions prevent verified
success; they are not silently ignored or attributed causally to the model.

Tool rules specify appropriate argument subsets, optional required operation
counts, redundancy bounds and genuinely necessary `after_tools` prerequisites.
The two evidence reads in the multi-step example can occur in either order.
Redundant allowed reads can lower tool accuracy without invalidating task success;
missing required qualifying operations can invalidate success. New intentional
writes differ from receipt-backed retries. Without annotations, appropriateness
and aggregate tool accuracy are unavailable, even if schemas can be validated.

## Evidence and reconciliation

Initial capture verifies the registry seed hash, full logical-state hash and
fixture hash. Final capture holds an execution claim and an exclusive sandbox
lease, preventing cooperating resume/reset/write operations during the snapshot.
Execution request, actor/tenant/run, permissions, incarnation and seed must match.

Frozen evidence includes both state projections, receipts, audits and a compact
agent-ledger projection. Event sequence/correlation, request/proposal/attempt
associations, counters, intent hashes and tool provenance are checked. The record
stores original ledger hashes/high-water references, not another raw journal with
document bodies. Input schemas and output-schema hashes retain contract identity.
Final answers are bounded/redacted by the existing agent. Local inspection is a
trusted developer action; no evaluation table or hidden oracle is exposed by MCP.

For writes, reconciliation computes the existing MCP receipt key through its
shared pure helper. Normalized existing DTOs establish the request hash. A matching
receipt must join exactly one actor/tenant/tool audit with the same task result.
Audits must form a valid chain from the initial task to final full state; unmatched
receipts/audits and unexplained mutations are evidence errors. Journal success
alone cannot establish a mutation.

A receipt and audit can prove a logical write despite a lost response. They do
not identify which retry committed it. Trace execution counts therefore use lower/
upper bounds for uncertain physical attempts, with at least one execution for a
proven logical write. Min/max checks pass only when the whole feasible interval
satisfies them; ambiguous counts remain unknown. Successful receipt replays are
tool executions, not additional mutations. Read completion relies on validated
durable MCP observations; there is no independent server-side read audit yet.

## Outcome and failure interpretation

Results separately record objective success (true/false/unknown), agent status,
denominator eligibility, findings and evidence references. Primary statuses are
successful, incorrect_final_state, missing_required_action, forbidden_side_effect,
incorrect_response, agent_execution_failure, budget_exhausted, authorization_failure,
incomplete_execution, invalid_scenario, evidence_error, infrastructure_failure and
not_executed. Multiple observed failure labels can coexist.

An expected refusal may succeed even when the agent status is permission_denied.
A task requiring only a confirmed mutation can succeed after interruption if all
its predicates are established. A task requiring an acknowledgement cannot pass
without that response. Fluent completion claims alone never establish success.

Labels cover tool/argument selection, unnecessary/missing operations, tool/model
execution failures, authorization, wrong/forbidden mutations, explicit duplicate
counts, recovery failure, final-answer failure, premature declarations, exhaustion,
incomplete execution/evidence and infrastructure errors. Context/observation
handling is a reserved label; it is not inferred from an incorrect answer. Labels
describe observations, not a claim about hidden reasoning or root cause.

See [metric definitions](metrics-definitions.md) for exact denominators. Invalid
setup/unsupported cases and evaluator failures are excluded with reasons. Started
timeouts, denials, ordinary provider/tool failures and exhaustion stay eligible.
Unexpected host execution errors are quarantined as infrastructure failures.
Missing evidence stays an eligible unverified outcome, with coverage/bounds;
it is not presented as a measured model error or a safe outcome.

## CLI workflow

Configure PostgreSQL using [database.md](database.md), then:

```powershell
uv sync --locked
docker compose up -d --wait postgres
uv run --locked opsdesk-eval run benchmarks/development/normal_order_status.json
uv run --locked opsdesk-eval run --development --config benchmarks/evaluation/development.json --repeat 2
uv run --locked opsdesk-eval list
uv run --locked opsdesk-eval list --experiment EXPERIMENT_ID
uv run --locked opsdesk-eval list --scenario normal_order_status
uv run --locked opsdesk-eval list --execution EXECUTION_ID
uv run --locked opsdesk-eval inspect TRIAL_ID --evidence
uv run --locked opsdesk-eval score TRIAL_ID
uv run --locked opsdesk-eval score TRIAL_ID --oracle PATH_TO_VERSIONED_ORACLE_JSON
uv run --locked opsdesk-eval report EXPERIMENT_ID
uv run --locked opsdesk-eval cleanup TRIAL_ID
uv run --locked pytest tests/evaluation
```

Replace printed IDs; commands work in PowerShell and Linux. `--transport memory`
still uses actual SDK protocol and PostgreSQL; default stdio starts real children.
JSON, CSV (including per-scenario rates and latency), and Markdown exports go to
unique ignored `artifacts/evaluations/EXPERIMENT_ID/REPORT_ID/` directories. No
previous files are overwritten. Run exits nonzero for infrastructure, invalid
scenario or evidence failures, after preserving its report; an ordinary negative
task outcome is valid research output. Unsupported injection cases are explicitly
not executed. Reports refuse silently omitting unscored trials after a runner crash;
use list/inspect to diagnose and recover sufficiently captured trials first.

Re-scoring reads frozen evidence, creates a fresh scoring ID/revision and stores
the full selected oracle plus evaluator source/version. Original execution and
evidence remain unchanged. Reports select the latest score per trial, never pool
revisions as additional trials. Preserve older exports for exact prior aggregates.
Scoring logic changes must increment `EVALUATOR_VERSION`; sidecar changes must
increment their annotation version. Scoring repair can reuse intact evidence;
bad fixture/execution setup requires a fresh trial.

## Coverage, cleanup and limits

Four of six development scenarios are executable: normal, multi-step, authorization
and ambiguous. Fixed fake plans are maintained independently of scoring expectations.
The multi-step fixture's available tools omit task-version discovery; its scripted
plan uses the fixed fixture version. This needs scenario/prompt review before
claiming a fully observable live benchmark task. The original specification is
preserved rather than silently expanding its permissions or exposing hidden state.
The recovery and prompt-injection scenarios are valid specifications but excluded
until Checkpoint 5 provides actual exposure/trigger evidence. Recovery's physical
execution-count expectation also needs review against timeout ambiguity. No attack
or recovery success numbers are manufactured. Held-out execution is disabled.

The runner only generates new `eval_*` sandboxes. Cleanup requires a persisted
runner-owned ID, the same marker and no resumable/active execution. Marker checking
is atomic inside the existing cleanup transaction. Incomplete runs retain their
sandbox and an explicit deferred outcome. Cleanup errors are reported separately.
The protected `docker_probe_01` and persistent PostgreSQL volume are never targets.

Runtime limits take the stricter experiment/scenario model-call, tool-call and
wall bounds, plus the existing graph/retry/context/output limits. Legacy cumulative
token/cost ceilings are **post-hoc accounting checks, not hard runtime spending
caps**; unknown usage/prices make compliance unknown. This limitation is explicit
in configuration/manifests/results. No paid API is called automatically.

Optional live use requires a privately set key and both exact model ID and opt-in:

```powershell
uv run --locked opsdesk-eval run benchmarks/development/normal_order_status.json --provider openai --model YOUR_MODEL_ID --live
```

Supply versioned prices through an experiment config for measurable cost. No live
evaluation was run during local validation. Hosted responses can vary despite
fixed settings. Production authentication, retention/encryption, automatic orphan
runner recovery, arbitrary external-service reconciliation, full interaction replay,
fault/attack injection and inferential multi-model comparisons remain future work.
