# Research design

## Objective and hypotheses

How reliably can LLM agents execute multi-step workflows using external tools
under normal conditions, tool failures, and prompt-injection attacks?

Measure tool choice and argument accuracy, recovery from transient/malformed
responses, unauthorized attempts versus actual execution, defensive tradeoffs,
provider latency/cost, and failure patterns by task category. Preregister these
directional hypotheses before held-out runs:

1. Guarded recovery improves success on recoverable faults, with added latency/cost.
2. Guarded data handling reduces attack success; it may over-refuse benign tasks.
3. Task success and unsafe execution differ across providers and workflow lengths.

No performance measurements or comparative claims exist in Checkpoint 0.

## Experimental unit and controls

One run is one versioned scenario, fixed initial snapshot, actor, agent variant,
provider/model revision and replicate seed. Fresh state for every run prevents
carryover. Pair baseline and guarded on the same scenario/replicate; randomize
execution order using a recorded seed, stratify by category and provider. Keep
tool contracts, policies, fixture, model settings and total budgets identical.
Guarded retries consume the same total budget. Record concurrency, hardware,
network region, provider routing, cache behavior and time of run. Start serially.

Target 100 scenarios: 20 normal, 20 multi-step, 20 tool failure, 20 prompt
injection, 10 authorization/unsafe-action, 10 ambiguous/impossible. Allocate
development/held-out by category as 12/8, 12/8, 12/8, 12/8, 6/4, 6/4 (60/40).
Category assignment uses a single primary label; secondary tags may overlap.
Count targets include both partitions. Six checked-in examples are development
specifications, not a completed benchmark and not empirical demonstrations.

Group near-duplicate fixture, attack and policy templates before splitting, so
paraphrases cannot cross partitions. Keep held-out requests, payloads and expected
outcomes in a separately access-controlled private artifact store. Publish only
hashes/version manifests to development tooling; lock them before model/prompt
tuning. Private GitHub visibility alone does not prevent developer leakage.

## Analysis plan

Pilot development runs to estimate variance and feasibility. Before held-out
evaluation, freeze configurations, scenario hashes, primary metric (Task Success
Rate), sample size, exclusions and analysis code. Initial plan: five replicates
per scenario/configuration, revisited using development variance and a documented
power or precision analysis. Do not stop early because results look favorable.
Report every category and macro-average category success as a secondary measure;
the primary aggregate is the run-weighted rate from the protocol.

Use scenario-cluster bootstrap confidence intervals (fixed analysis seed) for
rates and baseline/guarded paired differences; scenario, not individual retry or
replicate, is the resampling unit. Report denominator sizes, confidence level
(95%), missingness, provider-specific breakdowns and raw counts. Treat secondary
comparisons as exploratory, or preregister a multiple-comparison correction.
Report no confidence interval for an empty denominator. Small pilot estimates
are descriptive and cannot establish general safety or enterprise readiness.

Failures are multi-label: planning, tool selection, invalid arguments, grounding,
tool availability, recovery exhaustion, authorization denial, policy violation,
injection compliance, over-refusal, budget exhaustion and evaluator/infrastructure
error. Record a primary terminal cause plus all observed labels. Human review can
explain difficult cases but must not silently change frozen automated outcomes.

## Reproduction and limits

Persist Git SHA, lock hash, fixture/scenario/policy/prompt hashes, adapter and SDK
versions, model ID/revision, all sampling settings, seeds, price-table version and
immutable interaction artifacts. Temperature zero does **not** guarantee model
determinism. Live APIs can change routing, weights and availability.

Deterministic replay uses recorded model outputs, normalized requests and tool
responses with exact sequence/hash matching and a versioned virtual clock. Replay
may check evaluators and graph transitions without network calls; it cannot
estimate fresh model latency, live cost or counterfactual guard behavior after
the replay path diverges. Fail on divergence; do not reuse an unrelated response.

Synthetic OpsDesk limits external validity. Attacks are a curated sample, string
response checks are brittle, and authorization enforcement can conceal weak
agent intent. Report attempts separately from committed effects. Optional LLM
judges are secondary annotations with versioned prompts and human calibration;
they cannot substitute for state, audit and trace checks.
