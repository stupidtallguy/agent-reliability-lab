"""Local development registration, preflight and score-pinned evidence reconstruction."""

import argparse
import asyncio
import json
import os
import platform
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx2

from agent_reliability_lab.adversarial.contracts import HarnessSpec
from agent_reliability_lab.agent.config import ModelConfig
from agent_reliability_lab.evaluation.contracts import ExperimentConfig, ModelPrice, PriceBook
from agent_reliability_lab.evaluation.runner import provenance, read_case
from agent_reliability_lab.opsdesk.database import engine_from_env
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.platform.demo import assets
from agent_reliability_lab.research import live
from agent_reliability_lab.research.benchmark import (
    _arm_evidence,
    _context,
    execute_benchmark,
    run_inputs,
    schedule,
    starter_draft,
)
from agent_reliability_lab.research.benchmark_contracts import (
    CROSS_TEMPLATE_INTERVENTION,
    MULTIBLOCK_INTERVENTION,
    MULTIFAMILY_INTERVENTION,
    QUALIFICATION_INTERVENTION,
    BenchmarkDataset,
    BenchmarkProtocol,
)
from agent_reliability_lab.research.multifamily import (
    BLOCK_CASE_LIMITS,
    CASE_LIMITS,
    EXPANDED_CASE_LIMITS,
    QUALIFICATION_CASE,
    qualification_dataset,
    reviewed_dataset,
)
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
DISCOVERY_SCENARIO = "multi_step_resolve_task_discovery"
DISCOVERY_PROFILE = "local-ollama-discovery-1"
ABLATION_PROFILE = "local-ollama-ablation-1"
MULTIFAMILY_PROFILE = "local-ollama-multifamily-1"
EXPANDED_PROFILE = "local-ollama-expanded-1"
BLOCK_PROFILE = "local-ollama-blocks-1"
QUALIFICATION_PROFILE = "local-ollama-qualification-1"
MULTIBLOCK_PROFILE = "local-ollama-multiblock-1"
CROSS_TEMPLATE_PROFILE = "local-ollama-cross-template-1"
DISCOVERY_CASE = "benchmarks/controls/revisions/multi_step_resolve_task-discovery-v2.json"


def local_scenario(profile):
    if profile.uses_discovery:
        return DISCOVERY_SCENARIO
    return SMOKE_SCENARIO if profile.smoke else SCENARIO


def discovery_dataset(dataset):
    case, fingerprint, error = read_case(assets() / DISCOVERY_CASE)
    if error or not case or case.scenario.scenario_id != DISCOVERY_SCENARIO:
        raise ValueError("discovery case is missing or invalid")
    original = next(item for item in dataset.cases if item.scenario_id == SCENARIO)
    revised = original.model_copy(
        update=dict(
            case=case,
            template_id=DISCOVERY_SCENARIO,
            benchmark_version="1.1.0",
            harness=HarnessSpec(scenario_hash=fingerprint),
        )
    )
    return BenchmarkDataset(
        identity="cp22_discovery_development",
        created_at=dataset.created_at,
        author=dataset.author,
        benchmark_version="1.1.0",
        family_versions=dataset.family_versions | {"tool_use": "1.1.0"},
        cases=[revised],
    )


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


def case_limits(profile):
    if profile.qualification and not profile.cross_template:
        return {QUALIFICATION_CASE: BLOCK_CASE_LIMITS[QUALIFICATION_CASE]}
    if profile.blocks:
        return BLOCK_CASE_LIMITS
    return EXPANDED_CASE_LIMITS if profile.expanded else CASE_LIMITS


def _reviewed_local_dataset(profile):
    if profile.qualification and not profile.cross_template:
        return qualification_dataset()
    return reviewed_dataset(expanded=profile.expanded, blocks=profile.blocks)


def validate_local_plan(store, plan, protocol_ref):
    protocol = store.get(protocol_ref)
    profile = plan.model.local_profile if plan.kind == "benchmark_pilot_plan" else None
    if (
        profile is None
        or plan.kind != "benchmark_pilot_plan"
        or plan.protocol != protocol_ref
        or plan.mode not in {"ollama_local", "ollama_mock"}
        or protocol.mode != live.PROVIDER_PROTOCOL
        or protocol.model != ModelConfig(provider="ollama", model_id=TAG)
        or protocol.scenarios
        != (list(case_limits(profile)) if profile.multifamily else [local_scenario(profile)])
        or protocol.budgets.max_llm_calls != profile.calls_per_trial
        or protocol.budgets.max_output_tokens != 256
        or protocol.budgets.max_retries != 0
        or profile.factorial != (protocol.intervention == "guard_factorial_v1")
        or profile.multiblock != (protocol.intervention == MULTIBLOCK_INTERVENTION)
        or profile.cross_template != (protocol.intervention == CROSS_TEMPLATE_INTERVENTION)
        or (profile.qualification and profile.frozen_duration is None)
        != (protocol.intervention == QUALIFICATION_INTERVENTION)
        or (profile.multifamily and not profile.qualification)
        != (protocol.intervention == MULTIFAMILY_INTERVENTION)
    ):
        raise ValueError("incompatible local development plan")
    if profile.multifamily:
        if (
            store.get(protocol.dataset) != _reviewed_local_dataset(profile)
            or protocol.source_method != "git_python_lf_v1"
        ):
            raise ValueError("multifamily plan does not pin the reviewed cases and source method")
    elif profile.uses_discovery:
        dataset = store.get(protocol.dataset)
        control, _, error = read_case(assets() / DISCOVERY_CASE)
        if (
            error
            or len(dataset.cases) != 1
            or dataset.cases[0].case != control
            or protocol.source_method != "git_python_lf_v1"
        ):
            raise ValueError("discovery plan does not pin the reviewed case and source method")
    return validate_plan(store, plan)


def register(store, profile, *, mock=False):
    guard_database(store)
    name = "ollama_" + uuid.uuid4().hex
    dataset, parent = starter_draft(identity=name)
    updates = {}
    if profile.uses_discovery:
        dataset = (
            _reviewed_local_dataset(profile) if profile.multifamily else discovery_dataset(dataset)
        )
        method = "git_python_lf_v1"
        source = provenance(ExperimentConfig(experimental_evaluator="1.7.0", source_method=method))
        updates = {
            k: source[k] for k in ("source_commit", "source_method", "source_hash", "lock_hash")
        }
    if not store.list(dataset.kind, dataset.identity):
        store.append(dataset)
    budgets = parent.budgets.model_copy(
        update=dict(
            max_llm_calls=profile.calls_per_trial,
            max_retries=0,
            max_tool_calls=8,
            model_timeout_seconds=90.0,
            max_wall_seconds=120.0,
            max_output_tokens=256,
        )
    )
    frozen_duration = profile.frozen_duration
    protocol = BenchmarkProtocol.model_validate_json(
        parent.model_copy(
            update=dict(
                mode=live.PROVIDER_PROTOCOL,
                scripts={},
                scenarios=(
                    list(case_limits(profile)) if profile.multifamily else [local_scenario(profile)]
                ),
                dataset=store.reference(dataset),
                benchmark_version=dataset.benchmark_version,
                **updates,
                repetitions=1 if profile.qualification and not profile.multiblock else 2,
                planned_pairs=profile.trials // 2 if not profile.smoke else 2,
                intervention=(
                    CROSS_TEMPLATE_INTERVENTION
                    if profile.cross_template
                    else MULTIBLOCK_INTERVENTION
                    if profile.multiblock
                    else QUALIFICATION_INTERVENTION
                    if profile.qualification
                    else MULTIFAMILY_INTERVENTION
                    if profile.multifamily
                    else "guard_factorial_v1"
                    if profile.factorial
                    else parent.intervention
                ),
                model=ModelConfig(provider="ollama", model_id=TAG),
                budgets=budgets,
                hypothesis=(
                    "Verify process isolation and evidence across four reviewed conditions."
                    if profile.cross_template
                    else "Measure process-level resource stability across two genuine blocks."
                    if profile.multiblock
                    else "Qualify genuine block execution and evidence reconstruction on one pair."
                    if profile.qualification
                    else "Validate conservative one-pair blocks and evidence recovery."
                    if profile.blocks
                    else "Compare combined guarding on task completion, boundary compliance, "
                    "and model-directed recovery across eight development templates."
                    if profile.expanded
                    else "A local tool-calling model can attempt the existing development task."
                ),
                allocation_rationale=(
                    "Four independent workers in reviewed case order with alternating arm order."
                    if profile.cross_template
                    else "Two independent workers, one pair per worker, with opposite arm orders."
                    if profile.multiblock
                    else "One pair with seed-selected arm order. No cross-pair counterbalancing."
                    if profile.qualification
                    else "One counterbalanced pair per process block with a fixed "
                    "512 MiB RAM floor."
                    if profile.blocks
                    else "Eight primary templates and two matched benign conditions, "
                    "two counterbalanced pairs per condition."
                    if profile.expanded
                    else "Four distinct development families in two counterbalanced blocks."
                    if profile.multifamily
                    else "Two complete factorial blocks, with the second reversing the first."
                    if profile.factorial
                    else "One template, opposite orders. Smoke takes one baseline arm."
                ),
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
    calls = profile.calls_per_trial * profile.trials
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
        run_deadline=(
            protocol.created_at + timedelta(seconds=frozen_duration)
            if frozen_duration is not None
            else None
        ),
        limits=PilotLimits(
            total_calls=calls,
            calls_per_scenario=(
                2 * profile.calls_per_trial
                if profile.cross_template
                else 4 * profile.calls_per_trial
                if profile.multifamily and not profile.qualification
                else calls
            ),
            retries_per_turn=0,
            maximum_input_tokens=4096,
            maximum_output_tokens=256,
            total_tokens=calls * 4352,
            maximum_usd=Decimal(0),
            duration_seconds=(
                frozen_duration
                if frozen_duration is not None
                else 300
                if profile.qualification
                else 3600
                if profile.blocks
                else 120 * (profile.trials + 1)
                if profile.explicit_factors
                else 600
            ),
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
        observed = await identity(
            http, profile.hardware, smoke=profile.smoke, profile_version=profile.version
        )
        if observed != profile:
            raise ValueError("installed model differs from frozen local profile")
    if profile.smoke:
        arms = [next(a for a in arms if a.slot == "slot_0001" and a.arm == "baseline")]
    broker = PilotBudgetBroker(store.engine, store.scope, plan, local_opt_in=True)
    broker.initialize()
    broker.open(plan, arms, resume_blocks=profile.blocks)
    by_arm = {(a.slot, a.arm): a for a in arms}

    def factory(run_ref, slot, arm, config):
        return OllamaModel(broker, plan, by_arm[(slot, arm)], run_ref, config, transport)

    return factory


def verify_discovery_arm(store, model, score, trial):
    """Check the captured arm before allocating another sandbox."""
    evidence = store.evaluations.trial(trial["trial_id"])["evidence"]
    if evidence is None or score.reconciliation.get("complete") is not True:
        raise ValueError("discovery trial evidence failed reconciliation")
    terminal = evidence["execution"].get("result") or {}
    if terminal.get("reason") in {
        "ollama_identity_changed",
        "ollama_identity_observation_unavailable",
        "ollama_model_unavailable",
        "ollama_local_identity_unverified",
        "ollama_returned_model_mismatch",
        "ollama_bound_breach",
        "ollama_discovery_unexpected_patch_schema",
        "ollama_busy",
    }:
        raise ValueError("local identity or exclusive execution failed during the discovery study")
    profile = model.plan.model.local_profile
    if profile.cross_template and (
        terminal.get("status") == "budget_exhausted"
        or terminal.get("reason")
        in {"ollama_context_overflow", "ollama_context_or_output_exceeded", "model_timeout"}
    ):
        raise ValueError("cross-template execution stopped at a frozen context or budget bound")
    cap = case_limits(profile)[model.arm.scenario] if profile.multifamily else 1
    if score.unsafe is True or len(evidence["audits"]) > cap:
        raise ValueError("unsafe or repeated mutation observed during the discovery study")
    rows = {
        event["attempt_id"]: event["body"]
        for event in model.broker.snapshot()
        if event["body"]["request"]["execution_id"] == evidence["execution_id"]
    }
    _verify_request(evidence, rows)
    if profile.cross_template and any(row["state"] != "settled" for row in rows.values()):
        raise ValueError("cross-template execution has an unsettled physical request")


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
        if args.action in {"verify", "block"}:
            from agent_reliability_lab.research.contracts import Reference
            from agent_reliability_lab.research.local_blocks import (
                execute_block,
                reconstruct_blocks,
            )

            receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
            ref = Reference.model_validate(receipt["plan"])
            plan = store.get(ref)
            if args.action == "block":
                if (
                    not args.allow_local
                    or not plan.model.local_profile
                    or args.digest != plan.model.local_profile.model_digest
                ):
                    raise ValueError("local opt-in and matching full model digest required")
                return await execute_block(store, ref, args.block, local_opt_in=True)
            if plan.model.local_profile and plan.model.local_profile.blocks:
                readonly = ResearchStore(
                    store.engine.execution_options(postgresql_readonly=True), store.scope
                )
                return reconstruct_blocks(readonly, ref)
            return reconstruct(store, receipt)
        if args.action == "freeze-blocks":
            from agent_reliability_lab.research.local_blocks import MEMORY_FLOOR, available_memory

            if available_memory() < MEMORY_FLOOR:
                raise ValueError("available physical memory is below the 512 MiB floor")
        verify_listener()
        hardware, pressure = machine()
        async with client() as http:
            profile = await identity(
                http,
                hardware,
                smoke=args.action == "smoke",
                profile_version=(
                    CROSS_TEMPLATE_PROFILE
                    if args.qualify_cross_template
                    else MULTIBLOCK_PROFILE
                    if args.qualify_two_blocks
                    else QUALIFICATION_PROFILE
                    if args.qualify_single_pair
                    else BLOCK_PROFILE
                    if args.action == "freeze-blocks"
                    else EXPANDED_PROFILE
                    if args.expanded
                    else MULTIFAMILY_PROFILE
                    if args.multifamily
                    else ABLATION_PROFILE
                    if args.ablation
                    else DISCOVERY_PROFILE
                    if args.discoverable
                    else "local-ollama-1"
                ),
            )
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
            if args.action == "freeze-blocks":
                return receipt
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
    parser.add_argument(
        "action", choices=["preflight", "smoke", "pilot", "verify", "freeze-blocks", "block"]
    )
    parser.add_argument("--pgdata", type=Path, required=True)
    parser.add_argument("--allow-local", action="store_true")
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument("--discoverable", action="store_true")
    profiles.add_argument("--ablation", action="store_true")
    profiles.add_argument("--multifamily", action="store_true")
    profiles.add_argument("--expanded", action="store_true")
    profiles.add_argument("--qualify-single-pair", action="store_true")
    profiles.add_argument("--qualify-two-blocks", action="store_true")
    profiles.add_argument("--qualify-cross-template", action="store_true")

    parser.add_argument("--digest")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--block", type=int)
    args = parser.parse_args()
    if (args.action == "block") != (args.block is not None):
        parser.error("--block is required only for the block action")
    if (
        args.qualify_single_pair or args.qualify_two_blocks or args.qualify_cross_template
    ) and args.action != "freeze-blocks":
        parser.error("qualification profiles require freeze-blocks")
    if args.action in {"freeze-blocks", "block"} and any(
        (args.expanded, args.multifamily, args.ablation, args.discoverable)
    ):
        parser.error("the block policy sets its own frozen profile")
    if args.action != "preflight" and not args.receipt:
        parser.error("--receipt is required")
    print(json.dumps(asyncio.run(command(args)), ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
