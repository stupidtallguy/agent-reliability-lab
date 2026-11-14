# Synthetic external effects

An explicit scripted agent may discover `queue_notification` only in a
reliability sandbox. A trusted host registers a sandbox incarnation and actor.
The adapter reuses signed MCP write identity, checks the current role and selects
the customer in the bound tenant. The request contains only a synthetic customer
ID and a fixed template choice. The standard benchmark, guarded configurations,
and existing eight-tool catalog are unaffected.

An owned disposable PostgreSQL database holds the additive
`opsdesk_reliability` schema. A successful local response certifies a committed
intent and outbox row. A provider attempt records submission. The local simulator
stores one provider response per notification identity in a separate transaction.
Dispatcher acknowledgment is recorded after the provider transaction and may be
lost. A retry after loss reuses the same provider identity and payload fingerprint.

| Observation | Evidence |
|---|---|
| Local intent recorded | Matching intent, stored receipt and outbox payload digest |
| Outbox pending | No durable dispatcher acknowledgment |
| Submitted | Durable provider dispatch without a provider record |
| Accepted or rejected | Durable synthetic provider record |
| Delivered or failed | Matching accepted provider request and a terminal callback |
| Unknown delivery | No verified terminal callback and no provider rejection |
| Contradictory delivery | Conflicting terminal callback states |

Callback IDs and sequence numbers must agree on replay. Out-of-order pending
events do not undo a terminal delivery. Conflicting terminal states remain
contradictory. The simulation uses explicit calls and no networks or messaging APIs.
The test suite covers timeout before acceptance, rejection, lost acknowledgment,
late confirmation, concurrent duplicate submissions, callback replay and a
dispatcher interruption between provider commit and acknowledgment.
