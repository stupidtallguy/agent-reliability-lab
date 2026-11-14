# Context drift

The model request keeps the existing canonical hash of ordered messages and tool
schemas. An optional extension of the sealed request adds instruction and model
configuration hashes, plus an ordered list of response fingerprints and synthetic
document IDs/versions. No prompt, tool-response body or credential is added to the
record. The schema hash, template hash and output limit remain available.

The analyzer verifies the sealed chain and joins each request start to its request
journal event. It checks identity, execution, turn, input hash and ordering. When
present, related exposure events must reference the same input and occur between
the journal request and decision. Equal input hashes establish equality under the
recorded canonicalization. Unequal hashes establish a change. Component hashes
locate observable differences when both records have them. Historical records
may only support whole-input comparison.

A retry of a tool can dispatch again under the same logical identity without
invoking the model. Model requests on the same turn represent a different
boundary from adjacent decision turns. A resumed journal segment is identified
separately. A changed model context cannot change the trusted idempotency key or
justify a conflicting replay. These checks establish local evidence integrity
within the seal boundary. Behavioral causation and provider authenticity require
additional evidence.

Run `tests/test_reliability_context.py` and the real PostgreSQL regression
`test_changed_model_input_does_not_change_signed_write_intent`.
