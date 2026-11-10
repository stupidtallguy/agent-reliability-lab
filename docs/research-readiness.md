# Research readiness at application 0.9.0

## Implemented engineering

The platform supports immutable oracle versions, reviewer declarations, exact-hash
attestations, conflict declarations, disagreements/adjudication, frozen studies and
amendments, composite dataset releases, equivalent-condition pairing, exact scoring
revision selection and family-aware descriptive analysis. Candidate 1.7.0 requires
complete implementation and experimental-unit identity. Reports retain selected
score IDs/revisions, renderer identity and unresolved population slots.

`opsdesk-lab review-workspace .local/review` exports authoring schemas and practical
instructions. `opsdesk-research validate FILE` validates without database writes;
`append FILE` is a trusted authorized registration action. Actual human submissions
require explicit `--human-attestation`. Identity declarations are not external identity
verification. Synthetic/machine attestations do not count as human approval.

The composite dataset release pins both partitions. Current coverage is **38 development
scenarios and 0 held-out**. Cross-partition template/family/scenario disjointness is
validated at registration. Empty held-out data establishes no held-out performance.

The 0.9 demo freezes seven matched scenario pairs with exact oracle/dataset/score
references and an immutable analysis result. Not-applicable metric pairs are separate
from in-scope unknowns. A pair alias or reused trial/execution cannot increase n.
Analysis registration recomputes its selected-score result before append.

## Pending genuine research actions

- Independent read-only audit of the exact delivered 0.9.0 commit/evaluator 1.7.0.
- Real independent oracle reviewers, declared conflicts and preserved disagreements.
- Human adjudication if needed; no automated approval or fabricated reviewers.
- Independently authored and reviewed held-out template families.
- Authorized preregistration with sample-size rationale, estimands, clustering,
  stopping/exclusion criteria, uncertainty and sensitivity methods.
- Separate explicit authorization for any optional live/paid model pilot.

A saved specification/template is not an approved preregistration. The dashboard
shows these missing prerequisites. The no-key demo is scripted infrastructure
validation; it cannot establish live-model reliability, defense superiority,
external provider authenticity, causal attack influence or production readiness.

## Trust and remaining limitations

Read-only dashboard connections use PostgreSQL read-only transactions; least-privilege
roles strengthen this boundary. Local launch context is trusted developer configuration,
not production authentication. Hashes detect changes relative to a trusted frozen
snapshot; a privileged administrator can alter data and recompute local hashes.
No external execution authenticity follows from a local seal.

Cross-directory legacy test helpers remain technical debt; new helpers reuse dedicated
support modules rather than pytest fixtures through imports. Historical cases lacking
explicit pairing identities remain unavailable for verified pairing. Old scorer predicates
and renderer semantics remain frozen even where later candidates correct defects.
Live request sealing/immutability remains bounded by the documented local database
trust boundary and its prior trigger protections, not a remote provider attestation.

See templates/README.md, statistical-methodology.md and release-readiness-v1.0.0.md.
