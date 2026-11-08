# AI Agent Reliability & Evaluation Lab

A reproducible lab for evaluating AI agent reliability, MCP tool use, failure
recovery, and prompt-injection resilience in a synthetic enterprise environment.

**Current status: Checkpoint 0 — Research Design, Architecture, and Repository
Foundation.** This repository validates benchmark specifications. It does not yet
run an agent, serve MCP tools, compute evaluation results, or provide a dashboard.
There are no benchmark results or performance/security claims.

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

## OpsDesk and planned architecture

OpsDesk is a fictional company with a document knowledge base, a business database
of synthetic customers/orders/payments/accounts, and a support task system.

```text
Request + trusted actor -> FastAPI -> LangGraph single-agent loop -> model adapter
                                           |
                              validation / authorization / approval
                                           |
                                      MCP v2 tools
                                           |
                                 isolated PostgreSQL state
                                           |
                            state + trace + response evaluation
                                           |
                               read-only Streamlit reports
```

All operations are narrow and tenant-scoped. No arbitrary SQL or destructive
agent tool is planned. Baseline and guarded agents share essential permissions,
write safeguards and budgets; guarded behavior adds bounded recovery and data
defenses. This is a single-agent design with interchangeable provider adapters.

## Implemented in Checkpoint 0

- A typed, installable `src/` Python package and strict Pydantic scenario models.
- Deterministic inline fixture contracts, actor roles, tool allowlists and approvals.
- Fault/attack configuration, final-state checks, mutation constraints, alternative
  success paths and optional attacker objectives.
- Six synthetic development scenario specifications, one per planned category.
- Schema unit tests, Ruff configuration, uv dependency locking and GitHub Actions CI.
- Architecture, tool contracts, threat model, research protocol and decision record.

The planned benchmark has approximately 100 scenarios: 20 normal, 20 multi-step,
20 recovery, 20 injection, 10 authorization and 10 ambiguous/impossible. Targets
include a 60/40 development/held-out split. Held-out content is deferred and will
be stored separately to reduce leakage. The checked-in examples are specifications,
not evaluation-ready tasks until runtime oracles are implemented and reviewed.

## Setup and validation

Supported: **CPython 3.11 and 3.12**; primary version **3.11**. Python 3.13+ is not
supported in this checkpoint. Use **uv 0.13.7**. No Docker daemon, database or model
credentials are required for Checkpoint 0. Run from the repository root:

```console
python -m pip install uv==0.13.7
uv sync --locked --extra stack
uv lock --check
uv run --locked python -c "import agent_reliability_lab; print(agent_reliability_lab.__version__)"
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

`uv sync --locked` alone installs the minimal schema package and development tools.
The `stack` extra installs and locks the future FastAPI, LangGraph 1, official MCP
SDK 2, Psycopg 3 and Streamlit dependencies for compatibility checks. CI validates
that full extra on Python 3.11/3.12. Provider SDKs are deferred until adapters exist.
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

`.env.example` reserves future sandbox settings and contains no credentials.
Copying it is optional for this checkpoint; no implemented code reads it.

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
  decisions/0001-initial-architecture.md
src/agent_reliability_lab/
  __init__.py
  benchmarks/__init__.py
  benchmarks/scenario.py
tests/test_scenarios.py
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
and [validation record](docs/checkpoint-0-validation.md) for assumptions and limits.

## Roadmap

Checkpoint 1 will implement isolated OpsDesk fixtures and authenticated MCP tools
with Docker/Compose. Later checkpoints add the LangGraph agent, evaluators and
injection harness, a reviewed benchmark, and live experiments/Streamlit reporting.
Each has a separate acceptance gate in [the roadmap](docs/roadmap.md). No later
checkpoint is included in this foundation.

Keep fixtures, payloads and traces synthetic. Do not connect production systems,
commit secrets or treat attack payload text as project instructions. This repository
is intended to remain **private** and has no publishing/deployment workflow.
