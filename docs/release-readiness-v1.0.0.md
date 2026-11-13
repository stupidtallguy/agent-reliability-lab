# v1.0.0 release gates

Application 1.0.0 is a local software release. Engineering verification of the
release commit is recorded in [Checkpoint 10](checkpoint-10-verification.md).

## Software gates

- Reproduce the six AUD16 counterexamples and fix remaining high or critical engineering defects.
- Verify both Python versions with real PostgreSQL/MCP, restart and product tests.
- Verify lock, lint, formatting, distributions, isolated installation and hosted CI.
- Verify the protected volume fingerprint and preserve historical evidence and renderers.
- Verify the read-only dashboard, scripted seven-case demo, downloads and cleanup.
- Verify Windows installation and execution or record the owner's acceptance of specific gaps.
- Verify the exact private remote commit before creating the annotated software tag.

The [engineering verification record](checkpoint-10-verification.md) describes local
checks. Hosted evidence is the [CI run for the release commit](https://github.com/stupidtallguy/agent-reliability-lab/actions/workflows/ci.yml).

## Separate research-study requirements

- [ ] Independently authored and reviewed held-out template families; currently 0.
- [ ] Approved study design and preregistration with sample-size rationale and missing-data rules.
- [ ] Explicit authorization for any optional paid/live-model pilot.

Oracle Review is outside the software release scope. The optional workspace and
historical oracle artifacts remain available. All 38 current scenarios are development data.

## Release boundary

The software release validates local installation, execution and reproducibility.
Research conclusions require an approved design and appropriate observations.
Production deployment would need authentication, least-privilege roles and operational hardening.
