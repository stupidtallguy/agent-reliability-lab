# Checkpoint 13 · Sealed catalogs and cluster-level design

CP13 adds a planning and leakage-audit workflow to the CP12 research store.
The existing benchmark runner still executes scripted development scenarios.
The confirmatory protocol has a fixed disabled execution state. It can be
registered without human approval. Machine checks establish structural
constraints and artifact integrity. They provide no independent human review,
semantic novelty guarantee, execution authorization, or result on real models.

## Catalog boundaries

The comparison inventory reads the 38 published development scenarios, checks
their scenario digests against the published partition manifest, and includes
the training and development inputs pinned by the CP12 protocol. It uses
available runtime sidecars and both historical and CP12 family assignments.
Published scenario IDs and authored CP12 scenario profiles can overlap within
development. Multiple known profiles for the same case can contribute checks
while the reported comparison count is based on unique case and partition.

The private catalog format is `opsdesk_private_heldout_v1`. The top-level JSON
fields are `format`, `benchmark_version`, `nonce`, and `cases`. Each case
contains a CP12 `BenchmarkCase` under `scenario`, an `origin` declaration,
an opaque provenance `source`, `lineage`, and a `coverage` list. Both the
case and embedded scenario use the held-out split. The fixtures and runtime
sidecars must contain all declared stimuli. The OracleSpec and harness must
pin the exact scenario hash. The allowed coverage tags are defined by
`Coverage` in [heldout_contracts.py](../src/agent_reliability_lab/research/heldout_contracts.py).
The catalog should cover distinct task and attack families across tool selection,
policy and authorization, injection and conflicting instructions, failures,
partial execution, multi-step workflows, recovery, and idempotency. Coverage
counts reflect declarations and exclude rejected cases. A label does not
prove that a case exercises a behavior.

No real held-out artifact is supplied. The test suite generates explicitly
synthetic controls, including a distinct passing input and deliberately
contaminated inputs. The existing development catalog is preserved. Keep
future stimuli on an access-controlled filesystem or private artifact store.

## Loading and leakage audit

- Use the suffix `.opsdesk-heldout.json`. Within a Git checkout, the loader
  accepts files only in the ignored, untracked `.local/held-out/` directory.
  An external private file with the same suffix also works. Use a fresh,
  uniformly random 32-byte nonce represented by 64 hexadecimal characters.
- Set `OPSDESK_PRIVATE_HELDOUT_CATALOG` to the file path on the auditing
  machine. The loader opens it only through an explicitly authorized audit.
  It verifies SHA-256 over the exact file bytes before parsing. Even whitespace
  changes invalidate the commitment. Use local access controls for confidentiality.
  The seal is a content commitment and contains no path, encryption key, or raw
  stimuli. Avoid placing the raw file anywhere in Git history.
- The Git index guard checks tracked private paths, the dedicated suffix, and
  the catalog marker in staged JSON, including renamed JSON. CI runs the same
  guard. It cannot detect stimuli pasted into arbitrary unrelated text. The
  application blocks persistence of raw held-out BenchmarkDatasets. The legacy
  evaluator keeps the existing `not_executed` exclusion for held-out scenarios
  while withholding their scenario bodies and scoped sidecars. Mixed runs
  require individually scoped development scripts if a script is supplied.
- The audit compares scenario identity, exact content, executable inputs, and
  normalized inputs. It checks template and attack-family identifiers and
  normalized attack-payload reuse. Normalized requests and exact normalized
  fixture document content can independently expose a cross-partition overlap.
  Normalization applies Unicode NFKC and case folding, tokenizes alphanumerics,
  and ignores punctuation, whitespace, and list ordering for content comparison.
- Significant lexical similarity uses token-set Jaccard over task requests and
  attack payloads. Structural similarity uses multiset Jaccard over field paths,
  scalar types, role, category, and available tools. Both thresholds and the
  minimum lexical length are frozen in the protocol. Defaults are 0.80 lexical,
  0.92 structural, and at least six tokens on each side. Exact and metadata
  checks run regardless of those thresholds.
- Any configured finding invalidates the catalog audit and excludes affected
  held-out cases from eligibility counts. No execution is attempted. Reports
  contain aggregate results, numeric similarities, and opaque case references
  derived from the private nonce, with no case labels, prompts, or payloads.
  Reports include the complete finding counts even when the bounded detail
  list is truncated. Exit 2 indicates that the audit ran and failed the policy.
  Invalid inputs, denied access, and integrity errors exit 1 without dumping
  stimuli.

Heuristics can overflag shared scaffolding and miss paraphrases or undeclared
lineage. Authors should use genuinely different stimuli and family structures.
Thresholds may be changed only through a new protocol version before conducting
the corresponding audit. The loader cannot establish the provenance or
authorship asserted in a private file.

## Frozen experimental design

Three append-only artifacts share the current research table. The catalog seal
pins the private file digest, case count, benchmark version, and exact public
comparison inventory. The confirmatory protocol pins the seal and CP12 protocol
and includes the leakage policy, planning assumptions, and order seed. The
analysis plan pins both the confirmatory protocol and catalog and binds the
method version, software runtime version, alpha, and seeds. Changes to the
protocol or plan require consecutive versions and an exact predecessor ref.

The primary estimand is the mean guarded-minus-baseline difference in verified
objective task success, with equal weight for independent template families and
equal weight for both arm orders within a family. Repetitions are balanced
within each family and contribute dependent observations. Both orders require
at least one complete eligible pair for a primary cluster contrast. Missing,
contradictory, excluded, or unverified pair outcomes remain missing. Report
planned-slot sensitivity bounds by assigning each unresolved difference −1
and +1. Pair ordinals and family identities must come from frozen allocation
and evidence before future experimental inference.

Use a two-sided Student t interval and test on template-cluster differences,
with 95% confidence at default alpha 0.05. Require at least 20 complete
clusters and nonzero variance. A single primary comparison uses the specified
alpha. Attack success, unauthorized attempts, prohibited effects, recovery,
refusals, duplicate effects and evidence completeness remain descriptive
secondary outcomes. CP12's exploratory method and historical scorers remain
unchanged. [NIST Student t critical values](https://itl.nist.gov/div898/handbook/eda/section3/eda3672.htm)

## Planning assumptions and sensitivity

The planner fixes probability of discordance `q` and mean paired difference
`delta`. Within a template cluster a share of discordant pairs favoring the
guarded arm is drawn from a beta distribution centered on
`(1 + delta/q)/2`. The beta concentration sets dependence of the signs among
discordant pairs. The output also reports the induced ICC of the actual paired
differences. Independent random pair missingness and exclusions, and whole
cluster dropout, reduce usable information. Each cluster allocates equal
repetitions to both orders. The model assumes no systematic order or carryover
effect and uses the same loss probability in both orders.

Each grid row reports simulated power, null rejection, and Wilson 95% Monte
Carlo intervals for both. A conditional 80% or 90% grid candidate requires the
lower power bound to meet the target and the upper null-rejection bound to be
within the declared tolerance above alpha. Bounds are pointwise. A report
returns no planning size without externally justified assumptions and a
scenario at the minimum meaningful effect. An externally justified report
selects a common passing grid point across the specified minimum-effect
sensitivity scenarios, if one exists. Simulated power remains model-conditional.
Template-family independence, informative loss, carryover, and model
misspecification need separate design checks before confirmatory work.
[Morris, White and Crowther on simulation design](https://doi.org/10.1002/sim.8086)

The bundled sensitivity inputs are illustrative and were specified without
using the CP12 pilot's observed effect. At alpha 0.05, with 1,500 simulations
and seed 34917, the first qualifying grid counts are

| Expected difference | Sign ICC | Pairs per cluster | 80% | 90% |
|---:|---:|---:|---:|---:|
| 6 pp | 0.40 | 4 | 320 | 480 |
| 6 pp | 0.40 | 8 | 240 | 320 |
| 12 pp | 0.10 | 4 | 60 | 80 |
| 12 pp | 0.60 | 4 | 80 | 120 |

No recommended study size is issued for this example.

## Reproduce

Run the public-safe checks with Python 3.11 or 3.12.

```sh
uv sync --locked --extra stack
uv run --locked opsdesk-research benchmark-guard
uv run --locked opsdesk-research benchmark-power benchmarks/research/example-cp13-power.json --historical-cp13
uv run --locked pytest -q tests/test_cp13.py -m 'not integration'
```

For a private audit, use the [CP12 disposable database and registration
instructions](checkpoint-12-benchmark-foundation.md#execute-and-reproduce)
through registration of the CP12 protocol. Skip its run step if only auditing.
Compute the private file's SHA-256 locally, set the environment variable, then
draft and freeze the content-free design. Use the actual file digest and case
count in place of the placeholders. The draft command does not open the
private file.

```sh
uv run --locked opsdesk-research --scope cp12_pilot benchmark-design-draft .local/cp12/protocol-ref.json .local/cp13 --sha256 SHA256 --count COUNT --power benchmarks/research/example-cp13-power.json
uv run --locked opsdesk-research --scope cp12_pilot append .local/cp13/catalog-seal.json
uv run --locked opsdesk-research --scope cp12_pilot append .local/cp13/confirmatory-protocol.json > .local/cp13/protocol-ref.json
uv run --locked opsdesk-research --scope cp12_pilot append .local/cp13/analysis-plan.json
uv run --locked opsdesk-research benchmark-power .local/cp13/confirmatory-protocol.json
uv run --locked opsdesk-research --scope cp12_pilot benchmark-heldout-audit .local/cp13/protocol-ref.json --authorize-private-read
```

Use PowerShell 7 for the redirection on Windows. The PostgreSQL test
in `tests/test_cp13.py` generates its own synthetic private fixture and
exercises the full draft, append, audit, and refusal-to-execute boundary.

Future work requires an actual independently prepared private corpus, a
justified meaningful effect and heterogeneity range, and an authorized execution
boundary that binds the eligible catalog and allocation. Live model execution
also needs an enforceable spend cap. CP13 performs zero real held-out runs.
