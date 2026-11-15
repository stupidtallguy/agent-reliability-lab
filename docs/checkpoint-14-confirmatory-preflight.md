# Checkpoint 14 · Confirmatory allocation and analysis

CP14 adds append-only allocations, a structural preflight and a read-only
analysis path. The exercised execution path is the existing CP12 scripted
development runner. Held-out and live-model execution remain disabled.

## Audit and power

Leakage policy 1.1.0 checks lexical and structural similarity between different
held-out template families and normalized attack payload reuse between different
attack families. Exact and normalized duplicates are checked even within a
family. Same-template-family variants are exempt from similarity thresholds.
Cross-partition checks remain active. Frozen 1.0.0 audits retain their rules.

Independent pair loss is `1 - (1 - missing) * (1 - excluded)`, with both
inputs in `[0,1)`. Feasible 80% and 90% designs are reported separately by
repetitions per cluster. A common grid point must meet the lower Monte Carlo
power bound and the upper null-calibration bound for every applicable
minimum-effect scenario using that repetition schedule. Preflight rechecks
the selected point. The CP13 additive-loss report remains reproducible via
`benchmark-power --historical-cp13`. It cannot qualify a CP14 allocation.
The example is illustrative and uses no estimated treatment effect from CP12.

## Allocation and evidence

A frozen allocation pins the protocol, analysis plan, catalog seal, audit
and power-design digests, seed, and chosen slots. It draws only actual
eligible template families. Each cluster retains all member scenarios as
opaque references and assigns equal numbers of baseline-first and
guarded-first pairs. Repetitions must cover every member. Verification
reconstructs the slots from the frozen references and audited private catalog.
Amendments require an exact predecessor. Synthetic allocations instead
match the existing CP12 development schedule and require the same order seed.

An allocation-bound synthetic run freezes its reference before trial creation.
Ordinary CP12 runs and reports retain their serialized format. Analysis uses
the existing evaluator report reconstruction, score revision and capture
checks. A partial run can pin specific report IDs. Unselected slots count as
missing selected evidence. A conflicting evidence reference blocks verification.

The primary estimand weights each template cluster and each arm order within
it equally. Each complete cluster needs at least one verified pair per order.
The report includes the standard error, degrees of freedom, two-sided t
statistic and p-value, registered interval and fixed 95% interval. Fewer than
20 complete clusters or zero variance withhold inference. Planned-slot bounds
assign unresolved differences `-1` and `+1`. Missing, contradictory, excluded,
unavailable, unresolved and inapplicable outcomes retain separate counts.
Secondary outcomes are descriptive. The analysis artifact pins its
allocation, evidence selection, result digest, method and producer Python
version. [NIST Student t critical values](https://itl.nist.gov/div898/handbook/eda/section3/eda3672.htm)

## Preflight and safety

Preflight accepts either a registered allocation or an analysis plan when no
allocation exists. It emits blocked codes for missing private input, failed
audit, synthetic provenance, insufficient eligible families, uncertified power
assumptions or scheduling, mismatched references, and absent or insufficient
budget. A structurally ready report still leaves execution disabled. Declared
private-authored provenance is required for actual readiness. Machine-generated
material is outside the supported private schema. The CP14 evidence adapter
verifies stored **synthetic** development runs. Sealed allocations have no
authorized real execution or evidence ingestion path in this release.

The budget contract pins a model allowlist, frozen configuration hash, total
and per-scenario calls, tokens, USD, duration, and retries. The pure admission
check refuses unknown reservation bounds and overspend before dispatch.
Enabling real execution later requires a serialized atomic host ledger,
trusted provider ceilings, a host-enforced deadline and explicit authorization.

`--authorize-private-read` is an explicit opt-in. Authentication and
confidentiality depend on private artifact-store or filesystem permissions.
SHA-256 checks a registered content commitment. Authorship, semantic
independence and independent human review remain unverified. No human approval
gate was added. Public Git and research artifacts contain opaque references,
commitments and redacted audits. This checkpoint supplied no real private corpus.

## Reproduce

Use [CP13 registration](checkpoint-13-heldout-statistical-design.md#reproduce)
in disposable PostgreSQL and save the analysis plan's append output to
`.local/cp13/analysis-ref.json`. Select an actual qualifying design for the
allocation. The numbers below illustrate the CLI. See the
[`FutureBudget` contract](../src/agent_reliability_lab/research/confirmatory_contracts.py).

```sh
uv run --locked opsdesk-research benchmark-power benchmarks/research/example-cp13-power.json
uv run --locked opsdesk-research --scope cp12_pilot benchmark-preflight .local/cp13/analysis-ref.json --authorize-private-read
uv run --locked opsdesk-research --scope cp12_pilot benchmark-allocation-draft .local/cp13/analysis-ref.json --clusters 40 --repetitions 4 --budget .local/future-budget.json --authorize-private-read > .local/allocation.json
uv run --locked opsdesk-research --scope cp12_pilot append .local/allocation.json --authorize-private-read > .local/allocation-ref.json
uv run --locked opsdesk-research --scope cp12_pilot benchmark-preflight .local/allocation-ref.json --authorize-private-read
```

For the synthetic exercise, draft with `--synthetic-development` using a CP12
protocol with equal even pair counts per family. Append the allocation and run
`benchmark-run PARENT_REF --synthetic-allocation ALLOCATION_REF`. Put the
returned Ref under `benchmark_result` in the evidence JSON. For incomplete
evidence use `partial_run` and `selected_reports` with exact slot-and-arm keys.
The analysis accepts a frozen allocation or registered analysis reference.
Add `--draft-identity NAME` to emit a registrable analysis.

```sh
uv run --locked opsdesk-research --scope cp12_pilot benchmark-confirmatory-analyze .local/allocation-ref.json --evidence .local/evidence-selection.json
uv run --locked pytest -q tests/test_cp14.py -m 'not integration'
```

The [PostgreSQL test](../tests/test_cp14.py) exercises full and partial
synthetic reconstruction and rejects an altered score revision.
