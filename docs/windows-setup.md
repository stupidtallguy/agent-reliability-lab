# Windows setup

Install CPython 3.11 or 3.12 and Docker Desktop with Linux containers. Start Docker Desktop and run these commands from the checkout in PowerShell.

```powershell
python -m pip install uv==0.13.7
$env:UV_PYTHON = '3.12'  # Or the absolute path to an installed interpreter.
$env:UV_PROJECT_ENVIRONMENT = Join-Path $PWD '.local/windows312'
& .\scripts\setup.ps1 -Test
uv run --locked --extra stack opsdesk-lab demo
```

Use a separate environment and `UV_PYTHON=3.11` for the other interpreter. The setup script checks the installed environment and disables automatic Python downloads. A successful `doctor` run includes the Python version, SDK versions, and Docker daemon status. Docker access is required for the full test workflow and demo. Close the dashboard with Ctrl+C and run the owned cleanup command.

```powershell
uv run --locked opsdesk-lab stop-demo
uv run --locked --extra stack opsdesk-lab test
uv run --locked opsdesk-lab stop-tests
```

Keep ports 55435, 55436 and 8501 free for demo PostgreSQL, test PostgreSQL and Streamlit respectively. Use `--port` for an alternate dashboard port. Compose project names and bundled file paths are fixed for the disposable launcher. Persistent PostgreSQL and protected research sandboxes are outside those projects. See [installation](installation.md) and [troubleshooting](troubleshooting.md).
