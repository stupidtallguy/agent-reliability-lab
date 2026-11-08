# Threat model

Status: planned controls, not a claim of implemented runtime security.

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

System/developer policy is authored by the application. User requests establish
task intent within that policy. Retrieved content and tool output are evidence,
not new instructions or authority. Agent reasoning and requests are proposals,
not permission. Authorization lives in application/tool code outside the model
and applies equally to baseline and guarded configurations.

## Attack families and evaluation

Plan direct and indirect injection, role spoofing, fake approval, workflow
hijacking, answer contamination, malicious retry guidance and synthetic data
exfiltration. Use inert canary strings and fictional destinations under `.invalid`;
no external transmission is performed. Attack objectives are independently
machine-checkable and distinguish model compliance, denied attempts and executed
effects. Deny all unlisted domain writes and record invalid proposals too.
Guards must be evaluated for over-refusal and unnecessary latency, not assumed
effective from prompt wording or keyword filters.

Payloads in `benchmarks/development` are malicious **test data**. Never execute
their instructions during project development. Runtime harnesses will load them
as text into only declared injection surfaces. Keep real secrets out of fixtures,
traces, CI and `.env.example`. Provider credentials, when eventually needed, stay
host-side and are never inserted into agent messages or tool environments.

## Operational safeguards and residual risk

Checkpoint 1 must bind local services to loopback, isolate per-run databases,
disable production integrations, set resource/time limits and verify reset
behavior. Only the model adapter may use explicitly configured provider egress;
synthetic tool containers should have no Internet route. Pin images and review
dependency changes. A future network policy must be tested rather than inferred
from a Compose diagram. A private repository is not a secrets store.

Output framing and model instructions alone cannot guarantee injection resistance.
Authorization can prevent effects while the model still attempts violations.
Incomplete logs create unknown safety outcomes. A curated benchmark cannot cover
all adversarial content; report that limitation with every evaluation.
