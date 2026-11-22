"""Local development registration, preflight and score-pinned evidence reconstruction."""

import argparse
import asyncio
import json
import os
import platform
import subprocess
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx2

from agent_reliability_lab.agent.config import ModelConfig
from agent_reliability_lab.evaluation.contracts import ModelPrice, PriceBook
from agent_reliability_lab.opsdesk.database import engine_from_env
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research import live
from agent_reliability_lab.research.benchmark import (
    _arm_evidence,
    _context,
    execute_benchmark,
    run_inputs,
    schedule,
    starter_draft,
)
from agent_reliability_lab.research.benchmark_contracts import BenchmarkProtocol
from agent_reliability_lab.research.ollama_model import TAG, OllamaModel, client, identity
from agent_reliability_lab.research.persistence import ResearchStore
from agent_reliability_lab.research.pilot import (
    _verify_request,
    publish_pilot,
    validate_plan,
    verify_pilot_report,
)
from agent_reliability_lab.research.pilot_budget import PilotBudgetBroker
from agent_reliability_lab.research.pilot_contracts import PilotLimits, PilotModel, PilotPlan

SCENARIO = "multi_step_resolve_task"
SMOKE_SCENARIO = "benign_create"


def _read_command(command):
    try:
        return subprocess.check_output(
            command, text=True, timeout=10, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def machine():
    cpu = platform.processor()
    memory = free = None
    if os.name == "nt":
        cpu = (
            _read_command(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Processor).Name",
                ]
            )
            or cpu
        )
        memory_info = _read_command(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_OperatingSystem | Select-Object "
                "TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json -Compress",
            ]
        )
        if memory_info:
            info = json.loads(memory_info)
            memory, free = info["TotalVisibleMemorySize"], info["FreePhysicalMemory"]
    hardware = dict(
        os=platform.system(),
        arch=platform.machine(),
        cpu=cpu,
        ram_kib=memory,
        gpu=_read_command(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]
        ),
    )
    return hardware, dict(
        free_ram_kib=free,
        free_gpu_memory=_read_command(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader"]
        ),
    )


def guard_database(store):
    live.require_disposable(store)
    if store.engine.url.host != "127.0.0.1" or store.engine.url.query:
        raise ValueError("explicit IPv4 loopback disposable database required")
    if live.PUBLIC_PROVIDER_NETWORK_ENABLED or live.GROQ_FREE_NETWORK_ENABLED:
        raise ValueError("external network fuses must be disabled")


def validate_local_plan(store, plan, protocol_ref):
    protocol = store.get(protocol_ref)
    if (
        plan.kind != "benchmark_pilot_plan"
        or plan.protocol != protocol_ref
        or plan.mode not in {"ollama_local", "ollama_mock"}
        or protocol.mode != live.PROVIDER_PROTOCOL
        or protocol.model != ModelConfig(provider="ollama", model_id=TAG)
        or protocol.scenarios != [SMOKE_SCENARIO if plan.model.local_profile.smoke else SCENARIO]
        or protocol.budgets.max_llm_calls != 4
        or protocol.budgets.max_output_tokens != 256
        or protocol.budgets.max_retries != 0
    ):
        raise ValueError("incompatible local development plan")
    return validate_plan(store, plan)


def register(store, profile, *, mock=False):
    guard_database(store)
    name = "ollama_" + uuid.uuid4().hex
    dataset, parent = starter_draft(identity=name)
    if not store.list(dataset.kind, dataset.identity):
        store.append(dataset)
    budgets = parent.budgets.model_copy(
        update=dict(
            max_llm_calls=4,
            max_retries=0,
            max_tool_calls=8,
            model_timeout_seconds=90.0,
            max_wall_seconds=120.0,
            max_output_tokens=256,
        )
    )
    protocol = BenchmarkProtocol.model_validate_json(
        parent.model_copy(
            update=dict(
                mode=live.PROVIDER_PROTOCOL,
                scripts={},
                scenarios=[SMOKE_SCENARIO if profile.smoke else SCENARIO],
                planned_pairs=2,
                model=ModelConfig(provider="ollama", model_id=TAG),
                budgets=budgets,
                hypothesis="A local tool-calling model can attempt the existing development task.",
                allocation_rationale="One template, opposite orders. Smoke takes one baseline arm.",
            )
        ).model_dump_json()
    )
    ref = store.append(protocol)
    slots, _ = schedule(dataset, protocol)
    price = PriceBook(
        version="local-api-1",
        prices=[
            ModelPrice(
                provider="ollama",
                model_id=TAG,
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                provenance="Local API, excludes hardware and energy.",
                input_rate=Decimal(0),
                output_rate=Decimal(0),
            )
        ],
    )
    calls = 4 if profile.smoke else 16
    plan = PilotPlan(
        identity=name,
        author=protocol.author,
        created_at=protocol.created_at,
        mode="ollama_mock" if mock else "ollama_local",
        protocol=ref,
        schedule_hash=digest(slots),
        ledger_id=uuid.uuid4().hex,
        model=PilotModel(
            provider="ollama",
            model_id=TAG,
            allowed_models=(TAG,),
            endpoint="ollama_chat",
            local_profile=profile,
        ),
        pricing=price,
        pricing_hash=digest(price.model_dump(mode="json")),
        limits=PilotLimits(
            total_calls=calls,
            calls_per_scenario=calls,
            retries_per_turn=0,
            maximum_input_tokens=4096,
            maximum_output_tokens=256,
            total_tokens=calls * 4352,
            maximum_usd=Decimal(0),
            duration_seconds=600,
        ),
    )
    return store.append(plan)


async def open_local(store, plan, protocol_ref, transport):
    guard_database(store)
    arms = validate_local_plan(store, plan, protocol_ref)
    if transport is None:
        verify_listener()
    if (plan.mode == "ollama_mock") != (type(transport) is httpx2.MockTransport):
        raise ValueError("mock transport and frozen local mode differ")
    profile = plan.model.local_profile
    async with client(transport) as http:
        if await identity(http, profile.hardware, smoke=profile.smoke) != profile:
            raise ValueError("installed model differs from frozen local profile")
    if profile.smoke:
        arms = [next(a for a in arms if a.slot == "slot_0001" and a.arm == "baseline")]
    broker = PilotBudgetBroker(store.engine, store.scope, plan, local_opt_in=True)
    broker.initialize()
    broker.open(plan, arms)
    by_arm = {(a.slot, a.arm): a for a in arms}

    def factory(run_ref, slot, arm, config):
        return OllamaModel(broker, plan, by_arm[(slot, arm)], run_ref, config, transport)

    return factory


def reconstruct(store, receipt):
    plan = store.get(receipt["plan"])
    broker = PilotBudgetBroker(store.engine, store.scope, plan)
    if set(receipt) == {"plan"}:
        # A process may have stopped before returning a final evaluator report.
        return dict(
            interpretation=plan.mode,
            status="incomplete",
            plan=receipt["plan"],
            provider_events=broker.snapshot(),
        )
    if not plan.model.local_profile.smoke:
        report = store.get(receipt["report"])
        if report.plan != store.reference(plan):
            raise ValueError("local report belongs to another plan")
        return verify_pilot_report(store, report)
    run = store.get(receipt["run"])
    if run.pilot != store.reference(plan):
        raise ValueError("smoke run belongs to another plan")
    protocol, _, slots, catalog = run_inputs(store, run)
    slot = slots[0]
    ref = store.reference(run)
    score, arm = _arm_evidence(
        store,
        receipt["report_id"],
        _context(ref, run, protocol, slot, "baseline", local_mode=plan.mode),
        protocol,
        catalog[slot["scenario_id"]],
        digest([ref.content_hash, slot["slot"]])[:32],
    )
    events = broker.snapshot()
    rows = {event["attempt_id"]: event["body"] for event in events}
    evidence = store.evaluations.trial(arm["trial_id"])["evidence"]
    if evidence:
        _verify_request(evidence, rows)
    elif rows:
        raise ValueError("dispatched requests lack trial evidence")
    return dict(
        interpretation=plan.mode,
        smoke=True,
        profile=plan.model.local_profile.model_dump(),
        arm=arm,
        score=score.model_dump(mode="json"),
        evidence=evidence,
        provider_events=events,
    )


def verify_listener():
    # This release qualifies Windows hosts. Fail closed when the binding is unknown.
    addresses = _read_command(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "(Get-NetTCPConnection -State Listen -LocalPort 11434 -ErrorAction Stop).LocalAddress",
        ]
    )
    if addresses is None or set(addresses.splitlines()) != {"127.0.0.1"}:
        raise ValueError("Ollama listener must be verified on IPv4 loopback only")


async def command(args):
    store = ResearchStore(engine_from_env(), "local_ollama")
    try:
        guard_database(store)
        # Require the independently selected test cluster; never infer a production URL.
        with store.engine.connect() as conn:
            actual = conn.exec_driver_sql("SHOW data_directory").scalar_one()
            if Path(actual).resolve() != args.pgdata.resolve():
                raise ValueError("server storage differs from declared disposable PGDATA")
        if args.action == "verify":
            return reconstruct(store, json.loads(args.receipt.read_text(encoding="utf-8")))
        verify_listener()
        hardware, pressure = machine()
        async with client() as http:
            profile = await identity(http, hardware, smoke=args.action == "smoke")
            loaded = (await http.get("/api/ps")).raise_for_status().json()["models"]
        if args.action == "preflight":
            return dict(
                profile=profile.model_dump(),
                hardware_fingerprint=digest(hardware),
                current_resources=pressure,
                loaded_models=[
                    {
                        k: m.get(k)
                        for k in ("model", "digest", "size", "size_vram", "context_length")
                    }
                    for m in loaded
                ],
                disposable_database=store.engine.url.database,
                external_provider_network=False,
            )
        if not args.allow_local or args.digest != profile.model_digest:
            raise ValueError("local opt-in and matching full model digest required")
        with args.receipt.open("x", encoding="utf-8") as output:
            await store.initialize()
            ref = register(store, profile)
            plan = store.get(ref)
            receipt = {"plan": ref.model_dump(mode="json")}
            # Save the plan locator before the first inference, including on interruption.
            output.write(json.dumps(receipt))
            output.flush()
            run_ref, result = await execute_benchmark(
                store, plan.protocol, pilot_ref=ref, local_opt_in=True
            )
            if profile.smoke:
                receipt.update(run=run_ref.model_dump(mode="json"), report_id=result["report_id"])
            else:
                receipt["report"] = publish_pilot(store, ref, run_ref).model_dump(mode="json")
            output.seek(0)
            output.truncate()
            output.write(json.dumps(receipt))
        return reconstruct(store, receipt)
    finally:
        store.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preflight", "smoke", "pilot", "verify"])
    parser.add_argument("--pgdata", type=Path, required=True)
    parser.add_argument("--allow-local", action="store_true")
    parser.add_argument("--digest")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.action != "preflight" and not args.receipt:
        parser.error("--receipt is required")
    print(json.dumps(asyncio.run(command(args)), ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
