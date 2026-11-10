#!/usr/bin/env sh
set -eu
command -v uv >/dev/null 2>&1 || { echo 'Install uv: python -m pip install uv==0.13.7' >&2; exit 1; }
export UV_PYTHON_DOWNLOADS=never
uv sync --locked --extra stack
uv run --locked opsdesk-lab doctor
if [ "${1:-}" = "--test" ]; then uv run --locked pytest -m 'not integration'; fi
echo 'Ready: uv run --locked --extra stack opsdesk-lab demo'
