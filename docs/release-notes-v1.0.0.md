# Agent Reliability Lab v1.0.0

The first software release provides the local OpsDesk agent reliability platform. It includes isolated PostgreSQL sandboxes, an MCP tool layer, durable LangGraph execution, revision-pinned scoring and reports, paired analysis, and a read-only dashboard.

## Run the software

Install CPython 3.11 or 3.12, uv 0.13.7, and Docker Compose with a running Linux-container engine. From the private checkout, run `uv sync --locked --extra stack`, then `uv run --locked --extra stack opsdesk-lab demo`. Open [the local dashboard](http://127.0.0.1:8501). See [Windows setup](windows-setup.md), [installation](installation.md) and the [demo guide](demo-guide.md).

## Compatibility

Application 1.0.0 includes explicit experimental evaluator 1.7.0 and renderer 2.2.0. The default experimental evaluator remains 1.1.0. Historical score revisions, evidence, report pins, and renderer paths remain available. New candidate scores record implementation fingerprints. Use exact pinned revisions for historical reproduction and compatible cohorts for new reports.

## Engineering changes

- The candidate checks proposal metadata and ledger dispatch order against the original decision chain.
- Candidate reports require score-to-capture identity and use canonical attack outcomes in breakdowns.
- The dashboard labels synthetic demonstrations and observed trial splits.
- The demo and test launchers pin their owned disposable Compose projects and reject persistent or incorrectly bound containers.

## Research boundary

The seven-case scripted demonstration exercises both defense configurations without a paid API. All 38 catalog scenarios remain development data. Held-out data and a registered study are pending. Evaluator 1.7.0 remains a research candidate, with no external independent approval or evidence of causal attack influence, held-out generalization or live-model reliability. Oracle Review is outside software release requirements.

See the [engineering verification record](checkpoint-10-verification.md) and [release gates](release-readiness-v1.0.0.md).
