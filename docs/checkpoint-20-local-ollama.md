# CP20 local Ollama development experiment

The supported host is Windows with Ollama 0.40.16, a locally installed tool-capable GGUF `qwen3.5:4b`, and an explicitly owned loopback PostgreSQL cluster. The local protocol freezes the full manifest digest, quantization, template hash, hardware, source revision, source hash, dependency lock, schedule and evaluator 1.7.0. Request provenance captures the exact prompt and tool-schema fingerprints for each arm.

## Runtime and evidence

The CP12 runner creates a separate fictional OpsDesk sandbox for each trial. AgentExecution uses LangGraph, discovers MCP tools, and seals the model request. OllamaModel binds its native payload to that physical request, reserves capacity through the CP15 ledger and consumes one dispatch permit. The native client uses a fixed IPv4 loopback address, ignores proxy environment settings and disables redirects. The deployment fuses for cloud providers must both be closed. Model metadata and the full installed digest are checked before dispatch. The trusted local daemon and its files are part of the experiment's trust boundary.

The request uses 4096 context tokens, 256 generated tokens, seed 42, temperature zero and disabled thinking. Native history includes assistant calls with JSON argument objects and tool results with their corresponding name and ID. If a reply omits IDs, the host derives each ID from the physical request and call position. The existing graph validates the names, arguments, task scope and MCP authorization before any effect. Both truncation and context shifting are disabled. A length-limited reply is incomplete. See the [native API contracts](https://github.com/ollama/ollama/blob/v0.40.16/api/types.go).

The safety limits are four physical model calls, eight tool calls and 120 seconds per trial, including a 90-second per-request ceiling. Requests are sequential. A process lock prevents overlapping CP20 requests sharing the same host temporary directory. A timeout retains the dispatch in the ledger. An interrupted run has a plan locator for inspecting existing events without automatically replaying the request. JSON exports preserve runtime timing counters in nanoseconds, wall time in milliseconds, and independently measured tool and trial durations in the trial evidence. Token counters may be null. The local API has no per-token fee. Hardware, power and electricity costs are unmeasured.

The baseline smoke uses the development-only `benign_create` task. Its independent score and observed tool effect determine whether to proceed. The exploratory pilot freezes one `multi_step_resolve_task` template, two counterbalanced pairs, four isolated trials and at most 16 calls. The smoke has its own ledger outside the pilot. An engine failure, a truncated answer, a failed task and an unavailable measurement have distinct evidence. Two pairs cannot establish a population effect. Temperature zero and a seed do not guarantee identical generations.

## Reproduce on Windows PowerShell

Set up a fresh, private, test-owned PostgreSQL cluster. Use a free local port and a unique directory. Keep the directory to reproduce the reports. These commands assume PostgreSQL 18 binaries and an existing locked environment.

```powershell
$bin = "C:\Program Files\PostgreSQL\18\bin"
$pgdata = Join-Path $env:TEMP ("cp20-pg-" + [guid]::NewGuid().ToString("N"))
$port = 55482
& "$bin\initdb.exe" -D $pgdata -U cp20 -A trust --encoding=UTF8 --locale=C
if ($LASTEXITCODE) { throw "initdb failed" }
& "$bin\pg_ctl.exe" -D $pgdata -l "$pgdata\server.log" -o "-p $port -h 127.0.0.1" -w start
if ($LASTEXITCODE) { throw "test cluster startup failed" }
& "$bin\createdb.exe" -h 127.0.0.1 -p $port -U cp20 opsdesk_lab_test
if ($LASTEXITCODE) { throw "test database creation failed" }
$env:OPSDESK_DATABASE_URL = "postgresql+psycopg://cp20@127.0.0.1:$port/opsdesk_lab_test"
$env:OPSDESK_TEST_OWNED = "1"
$env:OPSDESK_ALLOW_SANDBOX = "1"
$module = "agent_reliability_lab.research.ollama"
uv sync --locked --extra stack
$check = uv run --locked python -m $module preflight --pgdata $pgdata | ConvertFrom-Json
$check
```

Inspect the full digest and hardware. Pass the independently checked digest explicitly. The receipt paths must be new for each experiment. Keep them outside tracked Git content. The verification command reads frozen data and requires no running Ollama daemon.

```powershell
$digest = "d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04"
uv run --locked python -m $module smoke --allow-local --digest $digest --pgdata $pgdata --receipt .local/smoke-ref.json > .local/smoke.json
uv run --locked python -m $module verify --pgdata $pgdata --receipt .local/smoke-ref.json
# After verifying a successful smoke, start the separately allocated pilot.
uv run --locked python -m $module pilot --allow-local --digest $digest --pgdata $pgdata --receipt .local/pilot-ref.json > .local/pilot.json
uv run --locked python -m $module verify --pgdata $pgdata --receipt .local/pilot-ref.json
& "$bin\pg_ctl.exe" -D $pgdata -m fast -w stop
```

CI uses an injected HTTP mock with actual PostgreSQL and MCP. The mock has a distinct execution mode and its trials retain the scripted classification. Genuine local trials use the live evaluator classification and the `ollama_local` research interpretation. No credentials, model downloads or external inference are needed for CI.
