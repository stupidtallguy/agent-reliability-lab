param([switch]$Test)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv first: python -m pip install uv==0.13.7'
}
$env:UV_PYTHON_DOWNLOADS = 'never'
uv sync --locked --extra stack
if ($LASTEXITCODE -ne 0) { throw 'Locked dependency installation failed.' }
uv run --locked opsdesk-lab doctor
if ($LASTEXITCODE -ne 0) { throw 'Environment validation failed.' }
if ($Test) {
    uv run --locked pytest -m 'not integration'
    if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed.' }
}
Write-Output 'Ready: uv run --locked --extra stack opsdesk-lab demo'
