# Synthetic evidence fixtures

These compact, fixed snapshots derive from the Checkpoint 4 scripted normal and
multi-step smoke runs through actual PostgreSQL and MCP. They support pure unit
tests without Docker. Catalog output schemas and raw journal result bodies are
omitted; source hashes/references and input schemas remain. `observed_seconds`
is the explicit synthetic test constant 0.25, not a benchmark measurement.
UUIDs/timestamps are fixed inert values in these files, not credentials.

Integration tests collect fresh independent evidence and do not use these files
as substitutes for the real database/protocol paths.
