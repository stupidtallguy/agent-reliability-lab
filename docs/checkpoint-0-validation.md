# Checkpoint 0 validation record

Date: 2026-11-08. These are engineering checks, not model evaluation results.

## Environment and scope

Validation host: Windows, CPython 3.11.9, uv 0.13.7. Python 3.11/3.12 are the
supported range and the CI matrix. Python 3.12 and Linux checks require CI; they
were not run locally. Docker and GitHub CLI are not installed on this host.
The project is a standalone repository at `E:\Agent_Reliability`; the existing
repository at `E:\` was not altered or marked globally safe.

## Observed checks

Commands below use `uv`; this host invokes the same pinned executable at
`.bootstrap\Scripts\uv.exe` because uv was not previously on PATH.

| Check | Command or method | Result |
| --- | --- | --- |
| Dependency lock | `uv lock --check` | 84 packages resolved, lock current |
| Full planned stack | `uv sync --locked --extra stack` | Installed successfully on Python 3.11.9 |
| Environment compatibility | `uv pip check` | All installed packages compatible |
| Scenario schema tests | `uv run --locked pytest` | 53 passed |
| Lint | `uv run --locked ruff check .` | Passed |
| Format | `uv run --locked ruff format --check .` | Passed |
| Stack imports | Import package, FastAPI, LangGraph, MCP, Psycopg and Streamlit | Passed, including `StateGraph`, v2 `Client` and `MCPServer` |
| Distribution build | `uv build` | Built wheel and source distribution |
| Installed wheel | Fresh isolated environment, import outside repository working directory | Passed |
| Package contents | Inspect wheel/source archive paths | No local environments, secrets, caches or Git internals |
| Documentation links | Resolve local Markdown link targets | Passed |
| Repository hygiene | Staged-file review, secret-pattern scan, `git diff --cached --check` | Passed before commit |

Schema tests cover all six example specifications, round trips, duplicate IDs,
broken/cross-tenant references, missing/extra fields, unknown tools/roles,
permission subsets, approval rules, budget bounds, injection requirements,
trigger collisions, invalid pointers, predicate bounds, empty outcomes and
alternative path contracts. They do not claim runtime authorization or evaluator
correctness. An initial lint line-length finding was corrected before final checks.
An early editable build ran before README creation and failed; the completed
project subsequently installed and built successfully.

The initial pip bootstrap transfer was truncated and failed its SHA-256 check.
It was discarded; ranged downloads were assembled and verified against PyPI's
full SHA-256 before installing uv. The project lock and hashes were not weakened.

## GitHub observations and limitations

The GitHub connector identifies `stupidtallguy` but cannot read this repository
(404). Git Credential Manager has that account and authenticated `git ls-remote`
successfully accesses the requested remote, initially with no refs. An
unauthenticated GitHub repository API request returns 404, consistent with a
private repository accessible only through the stored Git credential. No public
repository creation, visibility change or publication operation was performed.

The browser metadata check ended because the computer-use tool could not verify
the current browser URL. Direct authenticated repository metadata (including the
description and explicit visibility field) could not be inspected or edited.
The desired description is recorded verbatim in `pyproject.toml`; remote metadata
and default-branch settings should be verified with the commands below when CLI
access is available. The final handoff records the actual commit/push outcome.

```powershell
# Only if GitHub CLI is absent:
winget install --id GitHub.cli --exact
# Only if gh auth status reports no authenticated account:
gh auth login --hostname github.com --git-protocol https --web
gh repo view stupidtallguy/agent-reliability-lab --json url,isPrivate,defaultBranchRef,description
gh repo edit stupidtallguy/agent-reliability-lab --default-branch main --description "A reproducible lab for evaluating AI agent reliability, MCP tool use, failure recovery, and prompt-injection resilience."
```

If a future authenticated check establishes that the repository is absent, create
it privately and connect it without overwriting local history:

```powershell
Set-Location E:\Agent_Reliability
gh repo create stupidtallguy/agent-reliability-lab --private --description "A reproducible lab for evaluating AI agent reliability, MCP tool use, failure recovery, and prompt-injection resilience."
# origin is already configured in this checkout; add it only in a new checkout:
# git remote add origin https://github.com/stupidtallguy/agent-reliability-lab.git
git push --set-upstream origin main
```

No token was requested from the user or printed. No model credentials were used.
No agent, MCP server, API application, dashboard, database service, experiment
runner, held-out benchmark or metric evaluator is implemented. These are deferred
to the separately gated roadmap.
