# Oracle review workflow

Export schemas and a checklist with `opsdesk-lab review-workspace .local/review`.
An oracle defines legitimate behavior, prohibited behavior, evidence requirements,
metric eligibility and executable scoring rules. Reviewers must inspect the exact
specification and hash; naming a reviewer does not authenticate that person.

Author records using the exported schemas, then validate them with
`opsdesk-research validate FILE`. In an authorized disposable/research store,
`opsdesk-research --scope STUDY append FILE` appends a versioned artifact and
returns its hash reference. Register reviewer declarations before attestations.
Actual human submissions require `append FILE --human-attestation`; this is a
host-side assertion, not external identity verification. Automated demos must never
supply it. Synthetic attestations do not satisfy the human gate.

`review-status REFERENCE.json` reports pending review, disagreement, changes required
or declared approval. Review hashes and conflicts remain visible. Adjudication pins
the exact current review references and needs an appropriate declared human
adjudicator; stale review sets cannot silently resolve later disagreement. Revisions
append; they do not replace prior specifications/reviews. Confirmatory execution
requires separate explicit acceptance of the declared identity assurance and an audit
reference. Current demo specifications remain pending genuine independent review.
