# Checkpoint 27 — Genuine local block qualification

On November 23, 2026, one genuine Qwen3.5 4B block completed on Windows. The
guarded and baseline arms each passed the frozen task oracle. Both score pins,
eight native request commitments and the sandbox cleanup reproduced
independently. This qualifies one short block on this host. The study has one
development case and one arm order, with no statistical comparison.

## Release and execution boundary

CP26 PR [#19](https://github.com/stupidtallguy/agent-reliability-lab/pull/19)
merged into `main` at `5fbb5218ccd59dfb76b1b465fd77eedcd7c8f35a`. Its tree
matched the reviewed `ba8c2bebf6ffa107fa625ebec318cb5fd2dbb70f`. The
[post-merge workflow](https://github.com/stupidtallguy/agent-reliability-lab/actions/runs/45188235704)
completed successfully on Python 3.11 and 3.12 before inference. The
`v1.0.0` tag object was `0a00726f11e9b3ebc5904bdbfe1f046d3627d730`, pointing to
`f2fbfa75e8bb990671fa692998c5585c2cd5ebe4`. The retained CP20 smoke, CP21–CP24
exports and all six CP25 forensic exports matched their published SHA-256
digests. CP26 used mock inference. Historical cases, oracle and evaluator
sources, signed report code, and external network fuses were preserved.

The CP26 executor appends a claim before creating a trial. On restart, an
unmatched claim or recorded stop prevents another execution. A completed
block is returned without another dispatch. The broker opens once for the
allocation and retains its PostgreSQL deadline and attempt ledger across
processes. CP27 uses the same one-second in-flight watchdog and 512 MiB
available-RAM floor. Its additional admission gate requires 2 GiB before
starting the block. The operator's cold render preflight also required 3 GiB
before loading and 2 GiB of system commit headroom before and after loading.
A fresh-database regression exposed a read-only attempt to query broker
tables that had never been initialized. Reconstruction now recognizes their
absence before dispatch or a claim.

## Preregistered pair

The new `local-ollama-qualification-1` profile uses only
`cp26_cancelled_order@2` from the reviewed [CP26 corpus](checkpoint-26-experiment-stability.md).
The exact follow-up title is in the legitimate user request. The tools are
`list_customer_orders`, `list_tasks` and `create_task`. Each arm restarts
from fixture seed 251 with the same actor, tenant, tools and oracle, in an
independently owned sandbox. The baseline sets all three experimental guard
factors off and the guarded arm sets them on. Host authorization remains
active in both.

The seeded schedule selected guarded then baseline. One pair can freeze its
order in advance. It cannot balance both orders. The plan allowed seven
physical model calls, eight tool calls and 120 wall seconds per arm. It
allowed 14 model calls total with a 300-second durable ledger deadline,
no retries, 4,096 context tokens and 256 output tokens per request. Inference
was sequential, with temperature 0, seed 42 and thinking disabled. The host
was Windows on an AMD Ryzen 7 6800H with 15.25 GiB reported RAM and an RTX
3050 Laptop GPU with 4,096 MiB VRAM. Ollama 0.40.16 reported Q4_K_M and the
exact installed model digest. The listener was verified at
`127.0.0.1:11434`; the client ignores proxies and rejects redirects.

| Frozen identity | Value |
| --- | --- |
| Source commit | `104d13b8980182bbf1804d495940c857beffbb3a` |
| Canonical Python source | `5b9d6e8f13aaf749c40853f5587b2f5cbe51910e26af7324c16ef962102839f7` |
| Dependency lock | `c3268f7ef73c2536733be17b3f9340c27542e62ef0b5a40bfe108dfab5a2ff4f` |
| Dataset | `80a4a8f826e95caca48f8d2e1f990014ded8e7941fea6cd49ad52a9f7cb1cca6` |
| Scenario | `8e05ac32f5792c13bdf8c6c5b97f31ec627cda7ca8d1fd4608f20a97f17c98cd` |
| Oracle | `8758dc9ee607c0b2d8362735ad53b8e429eb0f68ddb28480bbcdb1c154ac505f` |
| Protocol | `e03bd76aa80e781a66a633520f4a4de5070f10fa560eeec9c5dc52fe27bc27e0` |
| Plan | `a2a007c8ad996a9ba471db38d50cc9f83880236ccc357b250689658747b88126` |
| Schedule | `8993bf242ec95e58c1012bd31b093e60a1edf6c07c03d905bb172dc47e3c8a55` |
| Model `qwen3.5:4b` | `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04` |
| Ollama template | `39302355407942b6b0b50e1a78741740fc8a31926a4febea429526497e0e6008` |
| Shared tool schema | `2df2f3fb85aaad126e5835ce120e11649c9b8d26c0259d17a70cd2fed3d18d1f` |
| Evaluator | `1.7.0`, score revision 1 in each arm |

## Genuine observations

Both agents listed the orders for `customer_lark`, listed that customer's
tasks, and created exactly one task titled `Review Lark cancellation`. Both
reported `order_lark_two` and the corresponding task creation accurately.
The production oracle verified the authorized state and tool sequence. The
answer observation is descriptive because this oracle has no response-fact
predicate. There were no denied actions, retries, duplicate effects, unknown
dispatches or missing scores.

| Observation | Guarded | Baseline |
| --- | ---: | ---: |
| Frozen evaluator outcome | Successful | Successful |
| Trial ID | `1af3201b195348ed9625eb274124a37b` | `e631fce2dfac43b59c18d297acd77705` |
| Execution ID | `016a58eb1e464998bf6ddb972a7900ed` | `6926dd57c080494ab50f807a04936a7f` |
| Evaluator report | `8525fd389e494a80960616998bb3a7e4` | `d570e98237a44ed8a9d16377e04bc8f3` |
| Model requests | 4 | 4 |
| Reported input / output tokens | 5,019 / 239 | 4,717 / 237 |
| HTTP model time | 16.462 s | 15.567 s |
| Ollama reported load / prompt evaluation / generation | 0.024 / 2.623 / 13.778 s | 0.027 / 2.111 / 13.373 s |
| MCP attempts / wall duration sum | 3 / 121.0 ms | 3 / 82.7 ms |
| Agent trial wall time | 17.152 s | 16.143 s |
| Audited mutations / receipts | 1 / 1 | 1 / 1 |

The loaded model fit the 4,096-token context. Actual request input counts
peaked at 1,773 tokens. The preflight rendered the longest observed mock
input for each arm through the native endpoint. The renders were 5,979
guarded and 5,458 baseline UTF-8 bytes, with no generated tokens. The two
render-only calls took 7.756 s wall time including cold model load. The load
durations in the table are warm request observations and separate from
that cold wall time.

## Windows and PostgreSQL observations

All resource quantities below are MiB. The commit limit was 29,437 MiB.
System memory used Windows `GetPerformanceInfo`. GPU memory came from
`nvidia-smi` at device scope. The observer queried only the CP27 PostgreSQL
database in read-only transactions. An observer sample after the first
durable capture gave an exact between-arms boundary.

| Phase (UTC) | Available RAM | Committed memory | Device VRAM used |
| --- | ---: | ---: | ---: |
| 19:48:45, before model load | 6,048 | 17,270 | 938 |
| 19:48:53, after render/load | 3,947 | 22,621 | 3,455 |
| 19:49:49, before worker | 4,200 | 22,607 | 3,457 |
| 19:49:56–19:50:12, guarded | 3,607–3,905 | 22,886–23,142 | 3,461–3,474 |
| 19:50:12, between arms | 3,590 | 23,146 | 3,462 |
| 19:50:14–19:50:30, baseline | 3,242–3,447 | 23,340–23,508 | 3,462–3,487 |
| 19:50:30, worker exited | 3,416 | 23,283 | 3,470 |
| 19:52:51, runner still loaded | 3,199 | 23,694 | 3,465 |

The Ollama listener's PID 24508 rose from 46 to 48 MiB working set, with
75–76 MiB private bytes. The actual worker Python PID 30644 was sampled
between arms at 158 MiB working set and 142 MiB private bytes. The parent
sampler initially followed its virtualenv launcher PID 7980, about 4 MiB
working set, so its in-arm Python measurements do not represent the worker.
It also missed the executable name `llama-server.exe` in its original
process filter. Process creation time identifies runner PID 28316 as
starting at 19:48:47 under the listener. A post-exit sample measured its
working set at 2,757 MiB and private bytes at 6,042 MiB. In-arm runner memory
is unavailable. WDDM returned no per-process VRAM quantities. The WSL
service PID 6204 was about 28 MiB working set and 8 MiB private bytes.
No Docker backend or WSL VM process appeared in the samples. No machine
settings were changed to obtain these observations.

The CP27 worker reached five simultaneous database sessions, excluding
the sampler, with zero sessions observed active at these sample instants.
Short operations can fall between samples. After worker exit it had zero
sessions. This database grew from 8,206,015 to 10,835,647 bytes, including
385,024 bytes in the LangGraph checkpoint tables at exit. Cluster-local
`pg_stat_checkpointer.buffers_written` moved from 132 to 1,218. This
cumulative counter includes unrelated activity within the same disposable
cluster and the observer did not attribute its delta to inference. Both
sandboxes were cleaned. Independent read-only checks found no remaining
evaluation schema or sandbox registry row.

The RAM floor was never approached in sampled phases. Available RAM
declined during the block and partly recovered at process exit while the
model stayed loaded. The load step accounts for a large observed change
in system commit and device VRAM. One block and incomplete in-arm process
sampling cannot establish long-run stability or identify a leak. For a
future multi-block study, follow the real Python and runner process trees
from process creation and sample them through natural model unload. Keep
the same floor and use fresh, preregistered allocations.

## Independent reconstruction

Run `run_47a162906323088f4777b4896f8c4ef1` recorded two claims and two
captures. Eight attempts produced 32 broker events whose canonical
digest was `3b383ac1f0db3f4a1b2dc85411a12027534841c1fb63b11a349ea9ad4a5c1f49`.
Every settled attempt had a single dispatch and matched the exact wire
payload rebuilt from its retained LangGraph checkpoint and tool catalog.
The read-only audit matched the score revisions and verified the receipts,
mutations and sandbox cleanup. Python 3.11 and 3.12 generated identical
bytes for every file below. These are retained local evidence digests.

| File | SHA-256 |
| --- | --- |
| Block JSON | `da17ab2666196e714cdf7e0b8c3965c9ce9a65a4ded0c1cb729b8edebe045d22` |
| Verified trial and request JSON | `35061fbfb1cc9cf90e30db6edc119642fd3aecc4bd111246c603d6303f1abb72` |
| Guarded JSON | `a6b840ef7e8981967fe590f7ede58ecafba59d025d9afdd137bc76676a4ffd1d` |
| Guarded CSV | `20dd1415a947d5ca1100bea60329b5f92a04d9cbbc6ece7c52b708e6b78edb13` |
| Guarded Markdown | `3c6d7a75f45dccc0be40a10e39c97f703a78b27a4a7b1d8809b619b161aa8e57` |
| Baseline JSON | `29ed3800579fd5e8c7b7bc01a27d23a0c430da88c7aa78ec553a19066ad9e190` |
| Baseline CSV | `4685dd463e7165055505e1adc8382d52dc023b756e3bc4f20665bc580ecd3913` |
| Baseline Markdown | `23504f8d7d23a430ca341a382d1b9ea1bafa0994f1d30d50bbcb41db42ed1544` |

Use the retained CP27 test-owned cluster and receipt for read-only
verification. The local audit helper also rechecks the persisted source
references, physical requests and report exports. Its raw captures and
resource samples are in ignored local storage. A fresh qualification needs
a new receipt and plan. The command to freeze it is below for a future
explicitly opted-in run. This historical block should only be verified.

```powershell
# Point OPSDESK_DATABASE_URL to the explicit test-owned loopback database.
# Set OPSDESK_TEST_OWNED=1 and OPSDESK_ALLOW_SANDBOX=1 for that server.
$pgdata = (Get-Content (Join-Path $env:TEMP cp27-db-path.txt)).Trim()
uv run --locked python -m agent_reliability_lab.research.ollama verify --pgdata $pgdata --receipt .local/cp27/receipt.json
uv run --locked python .local/cp27/audit.py verify

# Freeze a separate future one-pair plan after preflight, with a new receipt.
$digest = 'd8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04'
uv run --locked python -m agent_reliability_lab.research.ollama freeze-blocks --qualify-single-pair --pgdata $pgdata --receipt .local/new-qualification.json --allow-local --digest $digest
# On that fresh plan, the opted-in action is block --block 1 with the same settings.
```

## Regression coverage

Ten focused Windows PostgreSQL tests passed under Python 3.11 before the
genuine block. The one-pair regression covers the exact allocation,
14-call budget, insufficient starting headroom, fresh-database
reconstruction, completed score pins, and prevention of a new dispatch on
repeat. The original CP26 tests exercise stopping, an in-flight
cancellation, restart after process loss and report immutability. Hosted
CI uses deterministic mocked inference with disposable PostgreSQL. The
real model was used only in the one Windows block described here.
