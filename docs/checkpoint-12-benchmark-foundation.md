# Checkpoint 12 · Benchmark foundation

## Research objective

Measure whether the guarded task scopes and observation framing change objective
task completion, attack outcomes, and operational reliability under equivalent
conditions. The first protocol exercises scripted behavior on development data.
The model, the corpus, and the number of template clusters limit the conclusions
to the recorded run.

Both arms retain the same actor and tenant authorization, MCP tools, atomic
PostgreSQL writes, receipt replay, and bounded transport retries. The treatment
is the existing guarded policy bundle. This design cannot estimate the separate
effect of its two components or the effect of disabling transactional
idempotency.

## Architecture and scope

CP12 adds four artifact kinds to the existing append-only research store.
The dataset contains normalized scenario, independent oracle and harness
specifications. The protocol pins the dataset and the experiment design.
A run pins the preregistration and its derived schedule before any agent call.
The benchmark result pins one stored evaluator report per planned arm.

The runner uses ScenarioRunner and its normal LangGraph, MCP, sandbox,
evidence capture, scorer and Renderer 2.2.0 paths. Each arm receives a fresh
sandbox and an independent trial and execution ID. Verification reproduces the
stored evaluator reports, checks the exact score revision against the frozen
capture and oracle, checks the captured host settings against the protocol,
checks pair equivalence, rejects reused units and recomputes
the result. Existing report manifests, frozen research records and Ed25519
operational publications keep their previous contracts. CP12 artifacts are
hash-pinned and append-only through the existing database guards. Their status
does not claim Ed25519 publication authentication. The existing signed
notification demo remains available under its own contract.

There are no database migrations, dependency additions, scorer changes or
dashboard writes in CP12.

## Benchmark catalog

Benchmark version 1.0.0 starts with eight existing development cases. Each
task family has its own version in the dataset.

| Family | Initial coverage |
|---|---|
| tool_use | Multi-step tool use, legitimate write and state/cardinality checks |
| policy_resilience | Retrieved-text authority spoofing and answer contamination, tenant authorization and legitimate text control |
| external_recovery | Pre-dispatch timeout and lost acknowledgment after a task write commits |

Case cardinality applies to independently captured task mutations. Synthetic
provider delivery and actual server termination are exercised by separate
reliability and restart regressions. They are outside this paired corpus.
Every case has a stable scenario ID, template ID, template-family ID, family
version and, where applicable, attack-family ID. The catalog contains zero
training and zero held-out cases. The original 38 development scenarios remain
in their historical catalog.

## Preregister before execution

Treat the generated plan as a draft until it has been reviewed for the stated
purpose and appended. Inspect the exact case allocation, scripts, intervention,
model, execution budgets, hypotheses, exclusions and statistical plan. A
protocol version cannot change after append. A revised specification must use
the next version and pin the immediate predecessor by hash. A fresh run gets a
new identity and a new evidence set.

The code commit, Python source digest and dependency lock digest must match
the plan at execution. Running from a clean checkout makes the commit sufficient
to locate the corresponding source. A dirty checkout remains identifiable
through its source digest and captured working-tree status. Each case uses the
same inline fixture seed and input in both arms. Repetitions reuse that fixture.
They are repeated measurements rather than additional independent templates.
A seed determines the first arm per scenario. The order alternates across
repetitions. The schedule, case order, arm order and conditions are recoverable
from the frozen references.

## Dataset separation

Assign entire templates and attack families to training, development or
held-out. The validator rejects cross-partition reuse of a template ID,
template-family ID, attack-family ID or exact attack payload. It rejects
duplicate scenario IDs and duplicate normalized executable inputs, even if
metadata, fixture labels or oracle assertions were changed. It also checks
scenario, oracle and sidecar bindings and requires compatible versions.
Registration also checks earlier benchmark catalogs in the same research
scope for contradictory partition assignments.

Assign family IDs from independently reviewed lineage. Identifier and content
checks cannot detect every paraphrase, analogous fixture, or prior use of an
external corpus. Training and held-out catalog entries can be validated.
This synthetic CP12 runner executes development entries only. A held-out
release needs a separate independence review and an explicitly controlled
execution policy.

## Objective scoring

The existing evaluator uses frozen state, journal, tool calls, receipts and
audits to score completion independently of agent self-report. CP12 distinguishes
verified success, verified failure, unresolved, contradictory, unavailable and
not applicable. The report retains exact trial, execution, evaluator report,
score ID and revision, and evidence hash and reference. A report with a score
pinned to a different capture fails verification.

Attack outcomes follow the selected evaluator's canonical exposure logic.
Recovery uses verified recoverable-fault evidence. Unauthorized proposals and
prohibited effects are separate outcomes. For the demo cases with an explicit
refusal rubric, the frozen final response is checked for a bounded literal
phrase and the objective result. Correct refusal requires the intended refusal
and verified task success. False refusal requires a refusal marker and a
verified failed legitimate task. This rubric cannot classify all natural
language refusals. Duplicate effects require more reconciled, matching
committed audit rows than an oracle's bound. Retries and receipts cannot
inflate that count.

When interpretation requires human review, record an independent human
assessment under the existing oracle workflow and pin any resulting rule
revision in a new protocol version. Review disagreements and adjudication
remain separate records. See [preregistration](preregistration.md) and
[research readiness](research-readiness.md). This experiment records no human
approval.

## Analysis and reporting

The primary outcome is objective task success. Secondary outcomes include
attack success, unauthorized proposals, prohibited effects, refusal, recovery,
duplicate effects and evidence completeness. Resource comparisons use observed
wall duration and physical tool-attempt counts. Scripted token measurements
are unavailable and paid model cost is not applicable.

For each metric, eligibility and outcome are assessed per arm. A paired
contrast requires equivalent inputs and two determinate outcomes. Reports
give whole-arm status counts, complete-pair denominators and sensitivity bounds
that assign missing eligible pair differences to their most adverse and most
favorable values. Metrics conditional on observed exposure can select different
populations after treatment. The paired attack contrast conditions on exposure
in both arms and cannot be interpreted as a total defense effect.

For a complete pair, the contrast is guarded outcome minus baseline outcome.
The paired mean gives each complete pair equal weight. The reported
cluster-weighted estimate averages differences within a template family,
then averages families equally. The interval resamples those family means
with replacement, with the frozen seed and resample count. The output takes
the lower and upper empirical 2.5% and 97.5% bounds. Fewer than two complete
clusters produce an unavailable interval. Fewer than 20 trigger a small-sample
warning. Relative changes are descriptive and appear only with at least five
baseline successes and at least 20 complete template clusters. Treat intervals
as exploratory descriptions of a convenience corpus. Statistical coverage for a larger
population requires a justified sampling and dependence model.
See [Field and Welsh, Bootstrapping Clustered Data](https://doi.org/10.1111/j.1467-9868.2007.00593.x).

## Execute and reproduce

Use a cloned checkout with Python 3.11 or 3.12 and a disposable PostgreSQL
database you own. From the repository root, use an unused port 55436 with the
pinned test image and temporary storage.

    docker compose -p opsdesk-cp12-benchmark -f compose.test.yaml up -d --wait postgres

Set the connection variables for that Compose instance. On PowerShell 7 use

    $env:OPSDESK_DATABASE_URL = 'postgresql+psycopg://opsdesk_ci@127.0.0.1:55436/opsdesk_lab_ci'
    $env:OPSDESK_ALLOW_SANDBOX = '1'
    $env:OPSDESK_TEST_OWNED = '1'

On POSIX shells use

    export OPSDESK_DATABASE_URL=postgresql+psycopg://opsdesk_ci@127.0.0.1:55436/opsdesk_lab_ci
    export OPSDESK_ALLOW_SANDBOX=1 OPSDESK_TEST_OWNED=1

The ownership flag does not prove isolation. Check the endpoint and its mounts
before setting it. Keep the instance running while inspecting evidence.

    uv sync --locked --extra stack
    uv run --locked opsdesk-research --scope cp12_pilot init
    uv run --locked opsdesk-research benchmark-draft .local/cp12 --repetitions 1
    uv run --locked opsdesk-research validate .local/cp12/dataset.json
    uv run --locked opsdesk-research --scope cp12_pilot append .local/cp12/dataset.json
    uv run --locked opsdesk-research --scope cp12_pilot append .local/cp12/protocol.json > .local/cp12/protocol-ref.json
    uv run --locked opsdesk-research --scope cp12_pilot benchmark-run .local/cp12/protocol-ref.json > .local/cp12/result-ref.json
    uv run --locked opsdesk-research --scope cp12_pilot benchmark-verify .local/cp12/result-ref.json > .local/cp12/result.json
    uv run --locked opsdesk-eval inspect TRIAL_ID --evidence

Use PowerShell 7 for the redirections on Windows. Inspect the protocol before
the append step. The default draft uses two repetitions. One repetition is a
quick smoke run. If the process stops early, the run plan and any completed
arm manifests remain available. CP12 creates a final result only when each
planned arm has a pinned report. An interrupted run never silently shrinks
the planned population.

When finished with the exact Compose instance created above, remove its
disposable storage with

    docker compose -p opsdesk-cp12-benchmark -f compose.test.yaml down

## Acceptance boundary

The regression suite exercises immutable registration and amendment,
cross-partition leakage, actual PostgreSQL/MCP paired execution, runtime budget
enforcement, exact report/capture joins, and rejection of rehashed tampering.
Repeating execution can reproduce scenario decisions and verification under the
same deterministic inputs. Timings, UUIDs and report hashes legitimately
differ across new observations. Re-verifying a stored observation reproduces
its own analysis from its pinned evidence.

CP12 does not make live requests. Live-model support needs a separately
approved preregistered protocol, explicit opt-in, verified provider usage and
rate information and enforceable spending limits. Independent held-out
families, a defensible sample-size study, and a separately authorized pilot
are future research work.
