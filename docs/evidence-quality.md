# Evidence quality and operational metrics

Metric version: `reliability-1.0.0`. The evaluator version and renderer version
remain independent. For pinned evaluation reports, the applicable population is
the selected materialized score rows. For a synthetic notification, the scope is
the one recorded local intent. Frozen research denominators and exports retain
their original definitions.

| Measure | Numerator | Denominator |
|---|---|---|
| Outcome ascertainment | Eligible determinate task outcomes, or determinate provider outcomes for the demo | Materialized pinned rows, or local intents |
| Unknown outcome | Remaining unresolved or excluded rows, or unresolved notification outcomes | Same population as ascertainment |
| Chain completeness | Explicitly complete reconciliations, or a matched local receipt, acknowledgment and terminal outcome | Selected evidence chains |
| Contradiction | Rows with explicit consistency errors, or incompatible terminal callback states | Inspected rows with explicit diagnostics, or inspected intents |
| External confirmation | Terminal delivery, delivery failure or provider rejection | Local intents |
| Duplicate effect | Logical writes with more than one committed mutation | Writes with verified mutation count |
| Retry deduplication | Confirmed matching retries returning the original receipt | Resolved matching retries |
| Conflicting-intent rejection | Confirmed rejected conflicts | Observed resolved conflicts |
| Verified recovery | Faults confirmed recovered | Applicable resolved injected faults |
| Unknown commitment | Dispatched writes without proven commitment status | Dispatched logical writes |
| Receipt reconciliation | Matched receipts and committed effects | Writes requiring receipt verification |

An empty denominator or an unavailable population produces a null rate with a
reason. Historical rows without uniform contradiction diagnostics produce an
unavailable contradiction rate. Insufficient telemetry, absent receipts,
interruption, contradictory records and infrastructure gaps describe evidence
quality separately from agent behavior. A gap without a verifiable diagnosis
stays unknown.

The JSON, CSV and Markdown downloads for a synthetic notification use one
frozen document. JSON represents unavailable values with null. CSV uses empty
numeric fields and a reason. Markdown writes “Unavailable.” Existing historical
report exports are untouched.
