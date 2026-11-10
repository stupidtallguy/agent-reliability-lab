# Threat model

Status after Checkpoint 5: service/MCP authorization and transaction safeguards,
the durable agent, objective evaluator and controlled indirect-attack/fault harness
are implemented. Guarded mode adds explicit host task scopes and observation
framing; real model resistance remains unmeasured. Production HTTP authentication
and provider-comparison research remain planned. See [agent execution](agent-execution.md) for exact limits.

Assets include synthetic domain integrity, actor isolation, policy/approval
integrity, execution budgets, trace completeness and benchmark validity. The
attacker controls only designated sandbox documents or tool-response content.
The scenario author and infrastructure operator are trusted in this threat model;
compromised hosts, malicious maintainers and model-provider compromise are outside
scope and remain limitations. There are no real customers or integrations.

## Boundaries and controls

| Boundary | Risk | Required enforcement |
| --- | --- | --- |
| User input -> system/developer policy | User asks for forbidden tool/resource or claims a higher role | Trusted out-of-band identity; server policy outranks request; deny by default |
| Retrieved documents -> agent messages | Embedded instructions impersonate system/admin or redirect a workflow | Preserve provenance; mark as untrusted data; no promotion into privileged messages |
| Tool responses -> agent observations | Forged errors ask for credentials, permissions or another tool invocation | Typed envelopes, schema/size validation, untrusted-data framing; no credential tools |
| Model proposals -> application gate | Agent supplies unknown tool, malformed arguments, cross-tenant ID or forged approval | Validate every proposal; server role/resource checks; approvals bound to exact arguments |
| Approved proposal -> storage | Race, replay, duplicate write or timeout hides committed mutation | Transactional authorization, optimistic versions, stable idempotency and independent audit |
| Sandbox -> host/network | Attack tries shell/SQL execution or exfiltration | No such tools; isolated service network, fixed endpoints, no arbitrary URLs, no production egress |
| Trace -> evaluator/report | Injected text forges events or misleads an LLM judge | Structured append-only events; server audit reconciliation; deterministic state predicates |
| Development -> held-out benchmark | Tuning memorizes evaluation requests/attacks | Separate access, template-level split, frozen hashes and preregistration |
| Host launch -> MCP server | Model impersonates another actor/tenant or selects a run | Immutable host config, startup DB actor validation, no identity tool arguments, incarnation/seed pin across lifecycle lock |
| Host logical write -> MCP metadata | Caller invents retry keys or changes signed arguments | Host-allocated operation ID, HMAC over scoped identity and arguments, constant-time verification, service receipt conflict handling |
| Developer logs -> model observation | Diagnostics expose SQL, DSN, stack or paths | Generic tool errors with correlation IDs; stderr is developer-only and must not become model context |

System/developer policy is authored by the application. User requests establish
task intent within that policy. Retrieved content and tool output are evidence,
not new instructions or authority. Agent reasoning and requests are proposals,
not permission. Authorization lives in application/tool code outside the model
and applies equally to baseline and guarded configurations.

## Attack families and evaluation

The implemented primary threat is indirect injection through designated lower-trust
response fields, including authority spoofing, workflow hijacking, answer contamination
and local synthetic canary disclosure. Direct jailbreaks and real exfiltration are
outside the implemented benchmark. Use inert canary strings and fictional destinations under `.invalid`;
no external transmission is performed. Attack objectives are independently
machine-checkable and distinguish model compliance, denied attempts and executed
effects. Deny all unlisted domain writes and record invalid proposals too.
Guards must be evaluated for over-refusal and unnecessary latency, not assumed
effective from prompt wording or keyword filters.

Payloads in `benchmarks/development` are malicious **test data**. Never execute
their instructions during project development. The opt-in runtime loads them
as text into only declared lower-trust response surfaces. Keep real secrets out of fixtures,
traces, CI and `.env.example`. Provider credentials, when eventually needed, stay
host-side and are never inserted into agent messages or tool environments.

## Operational safeguards and residual risk

Compose binds PostgreSQL to loopback on a development bridge with `internal: false`;
container outbound networking is allowed. Stricter evaluation network isolation is
planned separately and must preserve a tested access path. Python uses registered
per-run schemas, ownership checks, restrictive cleanup and verified reset. The
database has statement/lock timeouts and Compose has a memory limit. There are no
production integrations. Schema isolation assumes cooperating trusted Python
callers; database owners can bypass it. Services are not an authentication layer.
Only the explicitly opted-in model adapter uses its fixed provider endpoint;
synthetic tool containers should have no Internet route. Pin images and review
dependency changes. A future network policy must be tested rather than inferred
from a Compose diagram. A private repository is not a secrets store.

Output framing and model instructions alone cannot guarantee injection resistance.
Local stdio binding/HMAC assumes a trusted OS account and host; it is not OAuth
or production authentication. Database owners can bypass service policy. Reset
clears receipts and rotates the marker; old bound clients/executions fail closed.
Active execution leases block reset/cleanup.
No HTTP transport is exposed; a future HTTP resource server must authenticate
principal/audience/tenant/run access before creating trusted context. Application
payload limits do not replace transport-level resource controls. Inert fixture
text is returned as data and does not prove general prompt-injection resilience.
Authorization can prevent effects while the model still attempts violations.
Incomplete logs create unknown safety outcomes. A curated benchmark cannot cover
all adversarial content; report that limitation with every evaluation.

## Checkpoint 3 execution boundary

The host persists actor/run/config association and checks its hash on resume.
Model call IDs are correlation data only. Logical write IDs and distinct attempt
IDs are host-assigned; intended arguments commit before dispatch. Session locks
prevent concurrent use of an execution. MCP services remain the authority for
tenant/role/scenario permissions, including after malicious user text.

Retrieved instructions remain `tool` message data with provenance. Only fixed
host policy is a system message. There is no shell, SQL, URL-fetch or filesystem
tool. Framing does not prove live-model injection resistance; scripted tests
verify execution boundaries, not model security performance.

JSON-only checkpoints avoid pickle. Known credentials, sensitive structured keys
and recognizable tokens are redacted before persistence; sensitive arguments are
rejected. SDK exceptions/signing metadata are not journaled. Redaction is best
effort: never supply real data/secrets as tasks. Database owners and trusted
Python callers can bypass local controls. Hosted journals need future access and
retention policy.

## 0.7.0 evidence and research boundaries

New execution seals and database triggers make completed decisions/journal/provenance
append-only. Frozen trial captures and reports are guarded against replacement.
Hashes detect changes; a privileged database owner can disable triggers or recompute
chains, so no external authenticity is claimed. Original proposals stay bounded and
redacted, separate from validated/authorized operations. Old records are not backfilled.

Oracle/review/preregistration records are trusted research-side inputs and never
enter model prompts or MCP tools. Reviewer identity is declared/unverified, not
production authentication. Human approval requires actual attestations; synthetic
records cannot satisfy it. The read-only research view uses read-only transactions,
not migration/scoring commands. A future UI needs its own deployment/access policy.
Cost-capped live execution is disabled when a safe reservation cannot be established.
No live or paid provider request is part of this milestone.

## 0.8.0 evidence consistency

Candidate 1.6 validates read-carrier attempt status/error/effect and sealed response
relationships as well as writes. Captured provider/model identity must match immutable
request-start declarations. Neither declaration nor hash authenticates a provider.
Original sealed model decisions remain evaluation evidence even before validation;
unsupported raw arguments remain rejected and never enter services. The protected
research database is not a test target; correction tests use separate disposable
PostgreSQL resources. No new authentication or security-effectiveness claim is made.


## Local product boundary (0.9.0)

The Streamlit dashboard reads through ResearchView with PostgreSQL read-only transactions.
It has no SQL, migration, cleanup, authorization-changing or model-execution UI. Downloaded
reports preserve pinned evaluator/renderer identities. Local hashes establish consistency
relative to trusted snapshots, not external authenticity. Candidate 1.7.0 still awaits
independent audit; see dashboard.md and evaluator-1.7.md. No production HTTP authentication
is claimed. Demo/test temporary trust authentication binds only to host loopback; use no
real credentials or sensitive data and do not expose these instances to a LAN.
