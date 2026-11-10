# v1.0.0 release gates

Application 0.9.0 is an engineering candidate, not an independently approved research
release. Do not create v1.0.0 until the exact delivered commit is reviewed.

## Automated engineering gates

- [ ] Independent reproduction of candidate counterexamples and historical reports.
- [ ] Both Python versions pass unit, real PostgreSQL/MCP, process restart and product tests.
- [ ] Lock, lint, formatting, wheel/sdist, isolated install/import and hosted CI pass.
- [x] Protected database fingerprints, all historical scores and original volume unchanged.
- [x] Local read-only dashboard and seven-case no-paid-API demo verified.
- [x] Windows/Linux setup, report exports, safe cleanup and documentation reviewed.
- [ ] Exact commit independently audited; candidate explicitly selected, default unchanged.
- [ ] Final release validation record and versioned distribution checksums preserved.

Checkpoint-9-validation.md records actual engineering evidence; unchecked here means
release approval is pending, not that unexecuted work is being represented as passed.

## Human and research gates

- [ ] Genuine independent oracle reviews with exact spec hashes and declared conflicts.
- [ ] Adjudication of disagreements by an appropriate independent human.
- [ ] Independently authored and reviewed held-out template families; currently 0.
- [ ] Authorized preregistration, sample-size rationale and missing-data/analysis approval.
- [ ] Explicit authorization for any optional paid/live-model pilot.

Software cannot complete human gates. Local identities/hashes do not verify reviewer
independence. The current 38 development scenarios must not be relabeled held-out.

## Release boundary

A software-only v1.0.0 can be considered after an independent audit and engineering
gates, with human research prerequisites explicitly pending and no generalized
research claims. A research-results release additionally requires the relevant human
gates and real authorized data collection. Production deployment also needs reviewed
authentication, least-privilege roles, operational hardening and external threat review.
No public deployment or production authentication is included here.

Recommended final milestone: audit the exact 0.9.0 commit, correct only reproduced
blockers under new semantics if persisted, then approve a narrowly labeled software
release. Do not manufacture held-out evidence, reviews or live-model findings.
