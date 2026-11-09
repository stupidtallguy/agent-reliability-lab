# Windows and Linux installation

Supported interpreters: CPython 3.11 and 3.12. Use uv 0.13.7 and Docker Desktop
(Linux containers) on Windows, or Docker Engine with Compose on Linux.

```console
python -m pip install uv==0.13.7
uv sync --locked --extra stack
uv lock --check
uv run --locked pytest -m 'not integration'
```

PowerShell, from the repository root:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env and set a disposable local POSTGRES_PASSWORD.
docker compose config --quiet
docker compose up -d --wait postgres
$env:OPSDESK_DATABASE_URL = 'postgresql+psycopg://opsdesk_lab:PASSWORD@127.0.0.1:55432/opsdesk_lab'
$env:OPSDESK_ALLOW_SANDBOX = '1'
uv run --locked pytest
uv run --locked opsdesk-research init
uv run --locked opsdesk-agent demo --case multi_step
```

Linux shell:

```bash
test -f .env || cp .env.example .env
# Edit .env and set a disposable local POSTGRES_PASSWORD.
docker compose config --quiet
docker compose up -d --wait postgres
export OPSDESK_DATABASE_URL='postgresql+psycopg://opsdesk_lab:PASSWORD@127.0.0.1:55432/opsdesk_lab'
export OPSDESK_ALLOW_SANDBOX=1
uv run --locked pytest
uv run --locked opsdesk-research init
uv run --locked opsdesk-agent demo --case multi_step
```

Replace PASSWORD with the matching URL-encoded disposable value. Compose reads
`.env`; Python reads shell variables. Never print or commit credentials. The official
PostgreSQL 18.6 image/digest and loopback binding are documented in [database.md](database.md).
The development bridge permits outbound access (`internal: false`); stronger
evaluation isolation requires a separate reviewed environment.

Agent/evaluation initialization applies additive migrations under advisory locks.
Research initialization reuses evaluation migrations. No manual arbitrary SQL or
database recreation is needed. See [research workflow](research-readiness.md) for
frozen specs/reviews and [reproducibility](reproducibility.md) for report selection.

To validate an installed wheel outside the checkout, install `dist/*.whl` into a
fresh environment using locked dependencies, then import `agent_reliability_lab`,
`agent`, `mcp`, `evaluation` and `research`. Unit tests require no database or API key;
integration tests require real PostgreSQL and explicit sandbox opt-in. Test each
interpreter separately; `uv run --python 3.12 --locked pytest` needs an already
installed 3.12 interpreter and a suitable environment.

`docker compose down` stops containers and retains the volume. Never use volume
deletion as cleanup. Reset/cleanup commands are only for explicitly owned disposable
runs; do not alter `docker_probe_01` or another execution's resources.
