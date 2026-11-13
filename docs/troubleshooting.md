# Troubleshooting

For Windows, pin `UV_PYTHON` to the installed interpreter and use a separate
`UV_PROJECT_ENVIRONMENT` per minor version. A Docker ownership error means the
fixed project/container failed its label, storage or port checks. Inspect the
container before retrying. Keep persistent data outside the demo/test projects.
If a candidate report rejects a score/capture mismatch, inspect the exact selected
revision and frozen capture. Preserve both records for diagnosis.

- Docker unavailable: start Docker Desktop in Linux-container mode, or the Docker
  Engine/Compose plugin. `opsdesk-lab doctor` reports availability without credentials.
- Port occupied: inspect the named owner; never remove an unrelated container. Demo
  uses 55435, tests use 55436, dashboard defaults to 8501 (`--port` can change the latter).
- Ownership refusal: the fixed name belongs to an unverified/persistent instance.
  Inspect it manually; the launcher deliberately refuses to replace it.
- Missing Streamlit: `uv sync --locked --extra stack`; include `--extra stack` in
  `uv run` commands to retain the optional product dependencies.
- Package-index connectivity: preserve the lock, retry the exact locked install with
  normal certificate validation. Do not substitute unpinned packages or disable TLS.
  A cached import is not proof of fresh installation; hosted CI checks a fresh install.
- PostgreSQL tests fail: use `opsdesk-lab test`, not the protected research URL.
  Integration tests deliberately fail without configuration; they do not skip silently.
- Report identity mismatch: pin compatible score IDs and oracle rules; do not relabel
  scores or silently choose latest revisions. Re-score appends a new revision.
- Malformed evidence: inspect the typed diagnostic and unknown coverage. Missing
  evidence cannot be repaired by inventing provenance or resetting a historical trial.
- Dashboard empty: set the trusted host research scope or run a fresh isolated demo.
  The UI never initializes schemas or creates reports on your behalf.
- Tmpfs full: export needed test/demo results, then stop only the verified owned
  temporary instance. Never delete a PostgreSQL volume as a shortcut.
