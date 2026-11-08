# AI Agent Reliability & Evaluation Lab

A reproducible lab for evaluating AI agent reliability, MCP tool use, failure
recovery, and prompt-injection resilience in a synthetic enterprise environment.

**Current status: Checkpoint 5 — Controlled Fault and Injection Evaluation
(version 0.6.0).** The existing MCP/LangGraph agent and independent evaluator now
support versioned fault interception, indirect prompt injection, verified exposure,
explicit baseline/guarded controls and paired isolated trials. The development
corpus has 12 fault, 12 attack and 8 benign cases. All six original scenarios are
preserved, with opt-in sidecars activating the two injection-dependent examples.
Scripted outcomes validate infrastructure, not live-model reliability or security.
No paid API request, dashboard or Checkpoint 6 comparison runs automatically.

## Motivation and research questions

Tool-using LLM agents can produce convincing answers while selecting the wrong
tool, making unauthorized requests, or failing after a transient error. Evaluating
the answer alone misses these failures. This project will compare final system
state, execution traces, and response content in controlled, repeatable workflows.

The central question is: **How reliably can LLM agents execute multi-step workflows
using external tools under normal conditions, tool failures, and prompt-injection
attacks?** We will study tool/argument accuracy, recovery, unauthorized attempts
and execution, defensive tradeoffs, provider latency/cost, and failure patterns
across task categories. Deterministic checks are primary; LLM judges are optional.

## OpsDesk and architecture

OpsDesk is a fictional company with a document knowledge base, a business database
of synthetic customers/orders/payments/accounts, and a support task system.

```text
Trusted CLI / Python host -> LangGraph single-agent loop <-> model adapter
                                           |
                              validation / authorization / approval
                                           |
                                      MCP v2 tools
                                           |
                                 isolated PostgreSQL state
                                           |
                            durable checkpoints + execution journal
                                           |
                         independent state/trace/response evaluation
                                           |
                          versioned JSON / CSV / Markdown reports
```

All operations are narrow and tenant-scoped. No arbitrary SQL or destructive
agent tool exists. Baseline and guarded configurations share essential
permissions, write safeguards and budgets. This remains a single-agent design
with interchangeable provider adapters.

## Implemented foundation

- A typed, installable `src/` Python package and strict Pydantic scenario models.
- Deterministic inline fixture contracts, actor roles, tool allowlists and approvals.
- Fault/attack configuration, final-state checks, mutation constraints, alternative
  success paths and optional attacker objectives.
- Six synthetic development scenario specifications, one per planned category.
- Schema unit tests, Ruff configuration, uv dependency locking and GitHub Actions CI.
- Architecture, tool contracts, threat model, research protocol and decision record.
- PostgreSQL schema and Alembic migrations using SQLAlchemy 2.0 Core/Psycopg 3.
- A deterministic baseline dataset and exact loaders for all six existing scenarios.
- Registered per-run schemas with guarded cleanup, reset and canonical snapshots.
- Eight typed internal services with tenant/role/scenario authorization, full-text
  document search, transactional audit, idempotency and optimistic task versions.
- PostgreSQL Compose configuration and real-database integration tests/CI.
- Three domain MCP servers with strict discovery schemas, structured output/error
  envelopes, untrusted provenance and immutable host-side actor/run binding.
- A reusable trusted SDK client with signed logical write identities and safe
  idempotent retries, plus real in-memory and stdio protocol tests.
- An explicit LangGraph graph, scripted/OpenAI adapters, execution budgets,
  bounded retries, PostgreSQL checkpoints, durable intents and an ordered journal.
- Actual MCP/PostgreSQL restart tests, including a process exit after a committed
  write; fake-model CLI demos and trace inspection.
- An independent scenario runner, consistent evidence snapshots, receipt/audit
  reconciliation, deterministic oracles and annotated tool-use scoring.
- Versioned PostgreSQL manifests/results, repeated trials, re-scoring, descriptive
  statistics and machine-readable reports with explicit missing-data coverage.

The planned benchmark has approximately 100 scenarios: 20 normal, 20 multi-step,
20 recovery, 20 injection, 10 authorization and 10 ambiguous/impossible. Targets
include a 60/40 development/held-out split. Held-out content is deferred and will
be stored separately to reduce leakage. The original six examples and the focused
32-case development corpus have scripted infrastructure controls. They still need
independent oracle review and opted-in live trials before model-level conclusions.

## Setup and validation

Supported: **CPython 3.11 and 3.12**; primary version **3.11**. Python 3.13+ is not
supported in this checkpoint. Use **uv 0.13.7**. Unit tests need no database, Docker
or model credentials. Run from the repository root:

```console
python -m pip install uv==0.13.7
uv sync --locked --extra stack
uv lock --check
uv run --locked python -c "import agent_reliability_lab; print(agent_reliability_lab.__version__)"
uv run --locked pytest -m 'not integration'
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

`uv sync --locked` installs the scenario/database package and development tools.
The core includes official MCP **2.3.0**, LangGraph **1.2.20**, PostgreSQL
checkpointer **3.2.0** and OpenAI SDK **3.46.0**. The `stack` extra installs planned
FastAPI/Streamlit dependencies. CI validates the full extra on Python 3.11/3.12.
`uv.lock` is committed; do not replace locked installation with an unconstrained
`pip install`. Update dependencies intentionally with `uv lock --upgrade`, review
the diff, and rerun checks before committing.

Validate an example without executing it:

```python
from pathlib import Path
from agent_reliability_lab.benchmarks import Scenario

scenario = Scenario.model_validate_json(
    Path("benchmarks/development/normal_order_status.json").read_text(encoding="utf-8")
)
print(scenario.scenario_id)
# Optional: Scenario.model_json_schema() exports the machine-readable JSON Schema.
```

For database work, copy `.env.example` to `.env`, set a disposable local password,
and start `docker compose up -d --wait postgres`. Compose reads `.env`; the Python
CLI reads `OPSDESK_DATABASE_URL` and `OPSDESK_ALLOW_SANDBOX=1` from the shell.
See the [Windows/Linux database guide](docs/database.md) for exact configuration,
migration, seed, inspect, reset, cleanup and shutdown commands. With that URL set:

```console
uv run --locked opsdesk provision --run demo_01 --baseline
uv run --locked opsdesk verify --run demo_01
uv run --locked opsdesk inspect --run demo_01
uv run --locked opsdesk reset --run demo_01
uv run --locked opsdesk cleanup --run demo_01
uv run --locked pytest -m integration
```

Integration tests require real PostgreSQL and fail if configuration/connectivity
is absent; they never substitute SQLite or silently skip a failed database.
`uv run --locked pytest` runs the complete suite with PostgreSQL configured.

## MCP tools and demonstration

The document server exposes `search_documents` and `get_document`; the read-only
business server exposes `get_order`, `get_customer` and `list_customer_orders`;
the task server exposes `list_tasks`, `create_task` and `update_task`.

With the database environment configured above:

```console
uv run --locked opsdesk-mcp demo
uv run --locked pytest tests/mcp -m 'not integration'
uv run --locked pytest tests/mcp -m integration
```

The demo provisions a unique run, starts real stdio children, discovers schemas,
reads an order, performs permitted task writes, repeats a write with the same
logical identity, demonstrates viewer denial, verifies reset and cleans up its
own sandbox. It refuses existing run names and preserves `docker_probe_01`.
No LLM or external AI service is involved.

Trusted launch configuration fixes actor, tenant and run; none are model tool
arguments. Write identity is supplied by the trusted client in signed metadata.
Services continue to enforce role/resource/scenario permissions. All returned
content is data with explicit untrusted provenance. No unauthenticated HTTP
endpoint or arbitrary SQL/filesystem tool is exposed. See [MCP workflow and
limitations](docs/mcp-integration.md) and [all eight tool contracts/examples](docs/tool-contracts.md).

The development Docker bridge uses `internal: false` to preserve verified Windows
host access at `127.0.0.1:55432`; outbound container networking is allowed. Stricter
evaluation isolation is a separate future configuration.

## Evaluation design

The protocol defines Task Success Rate, Tool-Call Accuracy, Recovery Rate,
Unsafe-Action Rate, Unauthorized Action Attempt Rate, Prompt-Injection Attack
Success Rate, nearest-rank p95 latency and Cost per Completed Task. Every metric
specifies denominators, unknown data and empty-set handling. A denied unauthorized
proposal is an attempt, not an executed action. Missing token usage is unknown,
not free. Temperature zero does not guarantee deterministic model responses.

Planned replay will verify recorded interactions without provider calls; live
evaluations will measure actual model behavior. Replay does not establish live
latency, fresh model cost, or behavior after a counterfactual path diverges.

## Repository map and documentation

```text
.github/workflows/ci.yml
benchmarks/development/          six synthetic JSON specifications
docs/
  architecture.md
  research-design.md
  evaluation-protocol.md
  tool-contracts.md
  threat-model.md
  roadmap.md
  checkpoint-0-validation.md
  checkpoint-1-validation.md
  checkpoint-2-validation.md
  database.md
  mcp-integration.md
  agent-execution.md, agent-tracing.md, checkpoint-3-validation.md
  evaluation-engine.md, metrics-definitions.md, checkpoint-4-validation.md
  decisions/0001-initial-architecture.md
  decisions/0002-postgresql-sandbox.md
  decisions/0003-bound-stdio-mcp.md
  decisions/0004-durable-agent.md
  decisions/0005-objective-evaluation.md
src/agent_reliability_lab/
  __init__.py
  benchmarks/__init__.py
  benchmarks/scenario.py
  opsdesk/
    cli.py, contracts.py, database.py, fixtures.py, services.py, tables.py
    data/baseline.json
    migrations/env.py
    migrations/versions/0001_opsdesk.py
  mcp/
    cli.py, client.py, context.py, contracts.py, errors.py
    servers/documents.py, business.py, tasks.py, shared.py
  agent/
    cli.py, config.py, state.py, graph.py, execution.py
    tool_adapter.py, persistence.py, tables.py, journal.py, errors.py, demo.py
    models/base.py, models/fake.py, models/openai.py
    migrations/env.py, migrations/versions/0001_agent.py
  evaluation/
    cli.py, contracts.py, runner.py, evidence.py, reconciliation.py
    oracles.py, tool_scoring.py, scoring.py, metrics.py, statistics.py
    persistence.py, tables.py, reporting.py, demo.py
    migrations/env.py, migrations/versions/0001_evaluation.py
tests/test_scenarios.py
tests/test_opsdesk_unit.py
tests/integration/              real PostgreSQL lifecycle/service tests
tests/mcp/                      in-memory protocol and real PostgreSQL/stdio tests
tests/agent/                    provider/unit, real MCP/persistence/restart tests
tests/evaluation/               oracle/metric controls and actual agent/MCP/PG trials
benchmarks/evaluation/development.json    optional versioned scoring configuration
compose.yaml
.env.example
.gitattributes
.gitignore
.python-version
pyproject.toml
uv.lock
README.md
```

Read [architecture](docs/architecture.md), [research design](docs/research-design.md),
[evaluation protocol](docs/evaluation-protocol.md), [tool contracts](docs/tool-contracts.md),
[threat model](docs/threat-model.md), [ADR 0001](docs/decisions/0001-initial-architecture.md)
and the [database guide](docs/database.md), [ADR 0002](docs/decisions/0002-postgresql-sandbox.md)
and [Checkpoint 2 validation](docs/checkpoint-2-validation.md) for assumptions and limits.

## Durable agent demonstration

With the same PostgreSQL environment configured:

```powershell
uv run --locked opsdesk-agent demo --case multi_step
uv run --locked opsdesk-agent demo --case viewer_denied
uv run --locked opsdesk-agent demo --case error
uv run --locked opsdesk-agent journal EXECUTION_ID
uv run --locked opsdesk-agent result EXECUTION_ID
uv run --locked pytest tests/agent
```

Replace `EXECUTION_ID` with a printed demo ID. Demos use actual stdio MCP and
unique disposable sandboxes. Fixed fake plans do not interpret arbitrary language.
The optional real model uses `--provider openai --model YOUR_MODEL_ID --live` and
a privately configured `OPENAI_API_KEY`; tests/CI need neither. No paid request
ran during local validation. [Agent execution](docs/agent-execution.md) documents
seven cases, trusted `ask`, resume, budgets and limits. [Tracing](docs/agent-tracing.md)
explains attempts versus receipts and response completion versus objective success.

## Objective evaluation

With the PostgreSQL environment configured, run the six development specifications
twice using the independent scripted controls:

```powershell
uv run --locked opsdesk-eval run --development --config benchmarks/evaluation/development.json --repeat 2
uv run --locked opsdesk-eval list --experiment EXPERIMENT_ID
uv run --locked opsdesk-eval inspect TRIAL_ID --evidence
uv run --locked opsdesk-eval score TRIAL_ID
uv run --locked opsdesk-eval report EXPERIMENT_ID
```

Use printed IDs. Each trial starts from a fresh fixture; exports go to ignored
`artifacts/evaluations/`. Missing evidence, usage/prices and unexecuted attacks are
explicit, never zero-filled. An authorized task refusal can succeed while a denied
unauthorized proposal is still counted. Re-scoring appends a result without another
agent call. Legacy cumulative token/cost ceilings are post-hoc checks, not runtime
spending caps. Live calls require an exact model ID and `--live`; none were run in
local validation. See [evaluation workflow](docs/evaluation-engine.md),
[exact metrics](docs/metrics-definitions.md) and [validation](docs/checkpoint-4-validation.md).

## Roadmap

Checkpoint 5 adds controlled faults, indirect attacks, exposure proof and paired
defense controls to independent scoring. Checkpoint 6, larger held-out research,
additional providers and Streamlit remain future work. See [the roadmap](docs/roadmap.md).
Local launch trusts the host; approval-required writes still fail closed.
Production authentication/HTTP and approval issuance remain planned.

Keep fixtures, payloads and traces synthetic. Do not connect production systems,
commit secrets or treat attack payload text as project instructions. This repository
is intended to remain **private** and has no publishing/deployment workflow.


## Faults, indirect attacks and defensive controls

After configuring PostgreSQL using the database guide:

```powershell
uv run --locked opsdesk-eval run --suite faults
uv run --locked opsdesk-eval run --suite attacks --defense guarded
uv run --locked opsdesk-eval run --suite controls
uv run --locked opsdesk-eval run --suite all --paired
uv run --locked opsdesk-eval compare BASELINE_EXPERIMENT_ID GUARDED_EXPERIMENT_ID
uv run --locked opsdesk-eval run --development --config benchmarks/evaluation/checkpoint5.json
uv run --locked pytest tests/adversarial
```

These commands use the fake model and real MCP/PostgreSQL; default transport is
stdio. `--transport memory` uses actual SDK protocol without subprocess startup.
Only `--provider openai --model YOUR_MODEL_ID --live` opts into paid model calls.
Inspect the printed trial IDs with `inspect TRIAL_ID --evidence`; re-score frozen
evidence with `score TRIAL_ID`. Exports remain under ignored `artifacts/evaluations/`.
Every trial uses a fresh owned sandbox; `docker_probe_01` and the volume are preserved.

Guarded mode adds observation framing and explicit host-authored task write scopes.
It does not derive intent from hidden evaluation goals or use a keyword blacklist.
Workflow hijacks and answer contamination have separate objectives; a denied
dangerous proposal is separate from an executed mutation. Framing alone is not
an injection-resistance guarantee. Missing exposure remains inconclusive.

New package: `adversarial/{contracts,runtime,triggers,exposure,defenses,objectives,
reporting,replay}.py`; new corpora: `benchmarks/{faults,attacks,controls}/development/`;
trusted config: `benchmarks/evaluation/checkpoint5.json`.
Read [fault injection](docs/fault-injection.md), [prompt-injection testing](docs/prompt-injection-testing.md),
[defensive configurations](docs/defensive-configurations.md), [ADR 0006](docs/decisions/0006-controlled-injection.md)
and [Checkpoint 5 validation](docs/checkpoint-5-validation.md).
