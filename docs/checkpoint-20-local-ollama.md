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


## Observed Windows smoke

On 2026-11-22 source `1cedfbe3bad10235a5285060d84fd7a25e33a3b3` ran Qwen3.5 4B Q4_K_M through the native loopback endpoint. The GGUF manifest digest was `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`. The Ryzen 7 6800H host reported 15,987,896 KiB of visible RAM and an RTX 3050 Laptop GPU with 4096 MiB VRAM (driver 621.24). The frozen hardware fingerprint was `079bdc2f7c91cf23a6ae1a85a10092d8b0e8d1acd0673762efba112bbde7bdc3`. After the smoke the daemon reported 3,743,384,858 loaded bytes, 1,879,813,650 in VRAM, and a 4096-token context. A subsequent sample showed 262 MiB free GPU memory and 3,729,204 KiB available host RAM. These are point samples.

| Request | Local input / generated tokens | HTTP wall time | Model load | Prompt evaluation | Generation |
| --- | ---: | ---: | ---: | ---: | ---: |
| Tool selection | 409 / 45 | 10.709 s | 7.619 s | 0.746 s | 2.337 s |
| Final answer | 741 / 67 | 3.982 s | 0.006 s | 0.450 s | 3.520 s |

The model selected `create_task(customer_id="customer_001", title="Shipment follow-up")`. The host accepted it. MCP took 76.36 ms and produced one receipt and one audited task creation. Total trial time was 15.224 s. The model answered “Task created successfully.” and supplied the resulting task ID, title, customer and status. The frozen response predicate requires the case-sensitive substring `Created`. The state and mutation checks passed, and the answer predicate failed. The independent evaluator recorded **incorrect_response**. No fault or refusal rubric applied. Zero retries, duplicate effects or unauthorized attempts were observed.

The evaluator report is `531e3a4b3931446a924a66167a0dc9bd`, trial `9b086e290d324a1499425f8892f622eb`, score revision 1, scoring ID `7e5805a4f6604561a33f77e8507eeb26`. The score pins evidence digest `ddddfcbb81dc78a4441a37f16a488d8c4ec16ed8ede5a5ec3cc5896ebf1719e5`. On the experiment host, pass `.local/cp20-smoke-ref.json` to the verification command against the retained test-owned cluster. The original JSON and its separate reconstruction had identical SHA-256 `df264ea62c9918f1726de3a58d1b189cac9169957759dd7d0fc66176eca7417a`. Export bytes on other platforms may use different line endings.

The four-trial study remained unexecuted after the unsuccessful objective smoke score. The paired-path results in CI come from mock HTTP. No real comparison between arms is available.
