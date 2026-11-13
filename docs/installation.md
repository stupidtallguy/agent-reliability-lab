# Windows, Linux and macOS installation

Supported: CPython 3.11/3.12, uv 0.13.7, Docker Desktop with Linux containers on
Windows/macOS or Docker Engine with Compose on Linux. Use the private repository
with your existing Git authentication; never paste credentials into commands.

```console
git clone https://github.com/stupidtallguy/agent-reliability-lab.git
cd agent-reliability-lab
python -m pip install uv==0.13.7
uv sync --locked --extra stack
uv run --locked --extra stack opsdesk-lab doctor
uv run --locked --extra stack opsdesk-lab demo
```

Alternatively, from PowerShell run `./scripts/setup.ps1 -Test`; from a POSIX shell
run `sh scripts/setup.sh --test`. Scripts install locked dependencies and check the
environment. They never configure paid APIs, print secrets or migrate protected databases.
Python must already be installed. Setup disables automatic interpreter downloads.
Use [Windows setup](windows-setup.md) for interpreter-specific PowerShell commands.

## Safe test workflow

```console
uv run --locked --extra stack opsdesk-lab test --unit-only
uv run --locked --extra stack opsdesk-lab test
uv run --locked --extra stack opsdesk-lab stop-tests
```

Full tests use `compose.test.yaml`, project opsdesk-tests, a labeled tmpfs instance
on 127.0.0.1:55436 with no volume. The launcher pins its Compose project and packaged
configuration independently of the benchmark/test workspace. It replaces inherited database
configuration with that dedicated test URL and explicit test ownership opt-in.
All PostgreSQL/MCP tests execute; unavailable PostgreSQL fails instead of skipping.
The instance remains available for inspection until explicitly stopped. Export needed
test evidence first: tmpfs data is disposable. Stopping it never touches the persistent
research database or docker_probe_01. Run each interpreter separately in its own locked
environment; hosted CI independently installs and tests both versions.

## Explicit disposable development services

The demo database on 55435 is separate from tests and persistent development on
55432. The demo initializes only its own instance automatically. For manual service
commands against that developer-owned disposable instance:

PowerShell:

```powershell
$env:OPSDESK_DATABASE_URL = 'postgresql+psycopg://opsdesk_demo@127.0.0.1:55435/opsdesk_lab_test'
$env:OPSDESK_ALLOW_SANDBOX = '1'
uv run --locked opsdesk provision --help
uv run --locked opsdesk-agent demo --case multi_step
uv run --locked opsdesk-eval run --suite all --transport memory --experimental-evaluator 1.7.0
```

Linux/macOS:

```bash
export OPSDESK_DATABASE_URL='postgresql+psycopg://opsdesk_demo@127.0.0.1:55435/opsdesk_lab_test'
export OPSDESK_ALLOW_SANDBOX=1
uv run --locked opsdesk provision --help
uv run --locked opsdesk-agent demo --case multi_step
uv run --locked opsdesk-eval run --suite all --transport memory --experimental-evaluator 1.7.0
```

Use `opsdesk --help` for explicit provision/inspect/reset/cleanup contracts. Never
select another person's run. Cleanup requires its trusted incarnation marker.
See database.md for the separately configured persistent local database; do not run
tests or candidate initialization against preserved historical evidence.

## Build and install distributions

```console
uv lock --check
uv build
uv venv .local/wheel
uv export --locked --extra stack --no-dev --no-emit-project --no-hashes --output-file .local/runtime.txt
```

Install the exported requirements and exact built wheel with `uv pip install --python`
pointing to `.local/wheel/Scripts/python.exe` (Windows) or `.local/wheel/bin/python`
(POSIX). Import from outside the checkout using Python `-I`; verify the package is
inside site-packages and its version matches installed metadata. Wheel resources
include synthetic benchmark specifications, the dependency lock and standalone demo/test Compose files.
Repeat the same installation in a fresh environment with the exact `.tar.gz` instead
of the wheel to check the source distribution. Run the demo from an installed
package with its `opsdesk-lab` executable and the `stack` requirements installed.
From a wheel outside Git, pass `--source-commit` for reproducible demo provenance.
No editable checkout import should be mistaken for an isolated installation check.

See troubleshooting.md for network, ownership, port and missing-data diagnostics.
