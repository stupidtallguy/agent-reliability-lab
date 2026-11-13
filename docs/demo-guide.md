# Deterministic end-to-end demonstration

```console
uv sync --locked --extra stack
uv run --locked --extra stack opsdesk-lab demo
```

Use `--no-ui` for automation; `--output PATH` chooses ignored exports. A fresh random
scope, trial IDs and pair group isolate every invocation. All model decisions come
from the scripted adapter. Actual LangGraph, MCP, PostgreSQL, objective scoring,
report persistence and research pairing execute; business services are not mocked.
The source commit is recorded (use `--source-commit SHA` outside a Git checkout).

Seven cases execute under both baseline and guarded configurations:

| Case | Demonstrates |
|---|---|
| normal_order_status | Legitimate read and factual response |
| benign_create | Permitted atomic task creation and receipt/audit reconciliation |
| fault_permanent_permission | Permanent tool denial; no unauthorized-intent inference from injected errors |
| fault_transient | Bounded recovery from a transient response |
| attack_viewer_attempt | Original unauthorized proposal, blocked by common authorization |
| attack_hijack | Malicious retrieval followed by a write; guarded scope enforcement |
| attack_body_answer | Answer contamination that observation framing alone does not prevent |

The demonstration deliberately includes unsuccessful cases. Inspect the trace and
compare attempts, effects, task success and attack outcome. These scripts establish
infrastructure behavior, not realistic model resistance or defense superiority.
Actual release verification outputs are recorded in [Checkpoint 10](checkpoint-10-verification.md).
Logical fixtures and scripted outcomes reproduce across runs. Timing, IDs and seals vary.
The dashboard labels new runs **Synthetic demonstration** from their frozen manifests.

The demo creates pending machine-authored oracle specifications, the 38/0 composite
dataset release, verified equivalent-condition pairs and an immutable selected-score
analysis artifact. It creates no reviewers, attestations, preregistration approval or
held-out cases. Generated reports live in `artifacts/evaluations` by default.

`opsdesk-lab stop-demo` stops only the verified owned temporary instance. Its database
is tmpfs and is disposable; export evidence first. No persistent volume is removed.
Repeated demo runs append fresh evidence rather than overwriting earlier scores.
Ports 55435 (demo), 55436 (test), and 8501 (dashboard) must be available.
