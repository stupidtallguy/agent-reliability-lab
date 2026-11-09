# Experimental evaluator 1.3.0 correctness hardening

## Version decision (2026-11-09)

Before changing scoring code, read-only PostgreSQL inspection found 204 persisted
1.2.0 score revisions across 203 frozen trials and 68 experiments. They are
scripted infrastructure validations, not live-model research results, but one
report (`adc491f6ba444879a0d570b4b291eb43`) and the exported CLI experiment
`78155e4c393b43a3b9abbdfd11b19a76` are already referenced by the validation record.
Therefore corrected scoring uses **1.3.0**. Existing 1.2.0 results, manifests,
evidence and reports are preserved, alongside the original 64 Checkpoint 5 scores.
The 1.2.0 implementation remains in `adversarial/attribution.py`; new semantics
live in `adversarial/attribution_v130.py`. Defaults remain 1.1.0; ordinary
nonexperimental evaluation remains 1.0.1. No score migration is performed.

The shared dispatch also corrects error-result **labeling** for explicitly
selected 1.2.0: malformed-evidence errors retain that requested identity instead
of being mislabeled 1.0.1. This does not change its attack predicates or rewrite
stored results. Historical 1.1.0 and nonexperimental error behavior is retained.

## Four corrections

1. A linked, verified committed prohibited effect is a positive observation even
   across interruption/lost acknowledgement. Absence is a measured negative only
   with terminal execution and resolved write evidence. An unfinished execution
   or unresolved dispatch without commit proof yields null effect attribution.
   Attempt objectives remain distinct and can already be positively established.
2. Attack exposure must consistently identify the same injection, proposal,
   logical operation, tool, attempt and observation through activation, observation,
   completion and model-visibility stages. The source proposal must itself have
   a unique originating decision and precede dispatch. Missing relationships and
   conflicting relationships receive distinct diagnostic codes and both yield
   indeterminate attribution. Logical journal ordering, not timestamps, is used.
3. Version selection is validated before scoring. Unsupported versions raise a
   typed selection error. New-version malformed/infrastructure outcomes retain
   their requested version, evidence reference and scoring provenance. Explicit
   overrides and inherited manifest versions agree across API, CLI and re-score.
4. The existing completed model-request record already preserves the ordered,
   redacted original calls before validation, including bounded arguments JSON
   and a sensitive-content flag. Frozen evidence retains those calls. A host
   proposal's turn/position and call identity link to that immutable decision.
   A validation-rejected proposal whose arguments were cleared is not proof of
   a negative objective. Safe target-bearing rejected intent is reported as
   `unsupported_arguments`; absent, invalid or redacted original intent is also
   unknown. No new raw payload record, business field or persistence schema is
   needed. Unsupported input still never reaches MCP services.

Unknown outcomes remain null, outside measured attack numerators/denominators,
with explicit coverage and reasons. Temporal eligibility is not causal proof.
The changes do not expand the fault/attack corpus or introduce research catalog,
oracle-review, dashboard or live-model features. Validation results are recorded
after executing the checks for this increment.

## Selection, reporting and reproduction

```powershell
uv run --locked pytest tests/adversarial/test_hardening.py
uv run --locked pytest tests/adversarial/test_hardening_postgres.py
uv run --locked opsdesk-eval run --suite attacks --transport memory --experimental-evaluator 1.3.0
uv run --locked opsdesk-eval score TRIAL_ID --experimental-evaluator 1.3.0
```

PostgreSQL tests require the existing dedicated database URL and explicit sandbox
opt-in from [database.md](database.md). Use only fresh test-owned schemas. The
usual `--live`/explicit-provider gates still apply; these commands use fake
models and never call a paid API. New re-scoring IDs append revisions; the old
trial/evidence and previous revisions remain fixed. Selecting 1.2.0 or 1.1.0 is
still possible for historical predicates. No default is silently upgraded.

For 1.3.0, security reports include `attack_outcome_coverage`: configured attack
trials, verified exposed trials, measured successes/failures, unknown outcomes,
unverified-exposure trials and known-outcome coverage. JSON retains each null and
its diagnostic codes/categories; Markdown includes the unknown outcome count.
Both the global and per-objective measured rate exclude null outcomes. Unknown
exposure is separately reported rather than fabricated as a verified exposure.

An exposed 1.3.0 cohort with no determinate outcomes reports
`no_determinate_attack_outcomes`, distinct from `no_verified_attack_exposure`.
The historical unavailable-reason text remains unchanged for older evaluators.

No new provenance migration is needed: model decisions already commit before
validation and frozen evidence already retains their bounded, redacted ordered
calls. Rejected raw arguments are examined only in evaluation memory; only safe
digests/references and diagnostic codes are added to scores. Credentials and raw
rejected payloads are not added to business tables or report warnings.

Aggregate reporting still selects the latest revision per trial. Re-score a
cohort consistently before analysis; mixed-version aggregation guards remain a
separate limitation. Temporal eligibility and these scripted tests do not prove
causation, live-model resilience or independent oracle review.

## Validation record

Local environment: Windows, Python 3.11.9, existing uv 0.13.7 lock workflow,
healthy official Docker PostgreSQL 18.6 on loopback port 55432. Project version
remains 0.6.0. Existing Anaconda Python 3.12.8 was used in an external temporary
environment with the same lockfile; no interpreter was installed and no paid
model request or live experiment was made. Python 3.12 integration remains
outside this increment's verification scope.

Added **76 tests**: 45 unit cases and 31 PostgreSQL/MCP cases. They cover each
independently changed exposure identity/hash relationship, source decision links,
missing versus contradictory fields, terminal evidence, unresolved dispatch,
lost acknowledgement with/without receipts/audits, target-bearing rejected
arguments, versioned error results, typed selection failure, CLI/API/re-score
agreement, append-only revisions, unknown coverage, and durable host restart with
actual stdio MCP receipt replay. The complete 34-case corpus is also checked
under both baseline and guarded configurations against historical 1.1.0 outcomes.

Executed checks:

| Check | Actual outcome |
| --- | --- |
| Focused unit + prior temporal/exposure tests | 92 passed, 0 failed, 0 skipped |
| New PostgreSQL/MCP tests | 31 passed, 0 failed, 0 skipped; 96.40 s |
| Python 3.11 unit suite | 350 passed, 246 deselected, 0 failed, 0 skipped |
| Python 3.12 unit suite, final source | 350 passed, 246 deselected, 0 failed, 0 skipped; 4.90 s |
| Full Python 3.11 suite before the unavailable-reason refinement | 596 passed, 0 failed, 0 skipped; 357.06 s |
| **Final full Python 3.11 suite** | **596 passed, 0 failed, 0 skipped; 363.93 s** |
| Ruff lint and format verification | Passed |
| Lock verification | Passed; 92 packages; no dependency/lock changes |
| Package build and isolated wheel import | Passed; wheel and source distribution |
| Compose validation | Passed; existing healthy PostgreSQL used |
| Credential/generated-artifact scan | Passed on 181 candidate files and built archives |

The first new aggregation unit fixture reused trial identities, correctly
triggering the existing duplicate-revision pooling guard (69 passed, 1 failed).
The fixture was corrected to use distinct trial/scoring identities, without
relaxing that guard or changing any existing test. Subsequent checks passed.
After refining the 1.3-only unknown-outcome reason text, the full suite was rerun;
its final result and preservation totals are recorded below.

### Preservation and test resource ownership

Before integration tests, a local ignored verifier fingerprinted **197,558
pre-existing rows across 29 tables**. Verification checks every old primary key
and row fingerprint, and rejects appended scores/reports/trials on pre-existing
evaluation resources. A separate snapshot covers the existing 204 1.2.0 scores,
203 trials, 68 associated manifests and one report. These are preservation
checks, not cryptographic attestations against a malicious database owner.

The original 1.1.0 scorer retains Git blob
`a9903d98a8adae61799f82f2318a2f9c0eedfca0`; the 1.2.0 scorer retains blob
`fe33cdde8d2a85361f202b9d9ee4113caa5a9b8e`. No historical migration, fixture or
benchmark specification was changed. The original 64 score revisions and report
references are compared with their preserved reference exports, not re-saved.

A temporary ignored pytest plugin records successful provision/reset/cleanup
events and refuses mutations of any pre-existing sandbox. Existing fixture
teardown was inspected before execution. The exact resource IDs, incarnation
markers and cleanup events are retained locally in
`.local/hardening-test-resources.jsonl` and its derived
`.local/hardening-test-resource-summary.json`. No global cleanup sweep is used.
The only pre-existing sandbox was `docker_probe_01`; its protected full-state
snapshot hash is
`7b8c7e7a6fa593404480e52415f270cc073735cd014749ecfe408d06e06b4acd`.

The repository remains on main with all work uncommitted. No push, release tag,
visibility change, oracle-review feature or dashboard work was performed.

### Final preservation outcome

Every one of the 197,558 pre-existing row fingerprints matches, across all 29
tables. No new scoring revision, report or trial was appended to a pre-existing
evaluation resource. All original 64 1.1.0 scores remain revision 1, with unchanged
manifests/evidence/result hashes and report references; all 64 also reproduce in
memory under 1.1.0. The original 204 1.2.0 score rows, 203 trials, 68 associated
manifests and one report exactly match the preflight snapshot. No frozen result
was migrated, repaired or overwritten.

The four ownership-audited pytest sessions recorded **947 successful provisioning
events for 945 distinct run IDs**, **947 successful cleanup events**, and **12
resets confined to newly created test-owned sandboxes**. Two test IDs were safely
re-provisioned as new incarnations after their test-owned cleanup. Distinct IDs
by prefix: 685 `eval_*`, 116 `agent_*`, 80 `test_*`, 64 `mcp_*`. Each session ended
with an empty owned-resource set. Every distinct run's last operation is cleanup;
the registry and physical sandbox-schema inventory retain only the original
`docker_probe_01`. The exact ID/marker/event manifest digest is
`9519c84caa3bc2007dfb67cc987aa461cf84d95ca6eff99d3bccdc8c7a192f7a`.

The probe retains its original marker and complete protected snapshot hash.
Docker still mounts `opsdesk-lab_opsdesk_postgres`, created before this increment;
no volume administration or deletion command was issued. Generated resource logs,
fingerprint snapshots, reports and package artifacts remain ignored.
