"""Immutable, one-pair local study blocks and an independent progress reader."""

import asyncio
import ctypes
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx2
import sqlalchemy as sa

from agent_reliability_lab.agent.persistence import ExecutionStore
from agent_reliability_lab.agent.provenance import verify as verify_provenance
from agent_reliability_lab.evaluation import tables as evaluation
from agent_reliability_lab.evaluation.contracts import ExperimentConfig
from agent_reliability_lab.evaluation.runner import ScenarioRunner, provenance
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import (
    _arm_evidence,
    _context,
    _source_matches,
    run_benchmark_arm,
    run_inputs,
    schedule,
)
from agent_reliability_lab.research.benchmark_contracts import BenchmarkBlockEvent, BenchmarkRun
from agent_reliability_lab.research.pairing import verify_pair
from agent_reliability_lab.research.pilot import _verify_request, validate_plan
from agent_reliability_lab.research.pilot_budget import PilotBudgetBroker, ledgers
from agent_reliability_lab.research.recovery_observations import task_recovery

MEMORY_FLOOR = 512 * 1024 * 1024
POLL_SECONDS = 1


def available_memory():
    if sys.platform != "win32":
        raise OSError("validated physical memory probe requires Windows")

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
            (field, ctypes.c_uint64)
            for field in (
                "total",
                "available",
                "page",
                "available_page",
                "virtual",
                "available_virtual",
                "extended",
            )
        ]

    state = MemoryStatus()
    state.length = ctypes.sizeof(state)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
        raise OSError("available physical memory observation failed")
    return state.available


def _sample(probe):
    try:
        value = probe()
    except OSError:
        return None
    return value if type(value) is int and value >= 0 else None


def _safe(sample):
    return sample is not None and sample >= MEMORY_FLOOR


def _run_identity(plan_ref):
    return "run_" + digest(["local_memory_blocks_v1", plan_ref.content_hash])[:32]


def _plan(store, reference):
    plan = store.get(reference)
    if (
        plan.kind != "benchmark_pilot_plan"
        or plan.model.local_profile is None
        or not plan.model.local_profile.blocks
        or plan.mode not in {"ollama_local", "ollama_mock"}
    ):
        raise ValueError("frozen CP26 local block plan required")
    return plan


def _read_run(store, plan_ref):
    records = store.list("benchmark_run", _run_identity(plan_ref))
    if not records:
        return None
    (row,) = records
    ref = {k: row[k] for k in ("kind", "identity", "version", "content_hash")}
    run = store.get(ref)
    if run.pilot != plan_ref:
        raise ValueError("block run differs from its frozen plan")
    return run


def _events(store, run):
    return [
        BenchmarkBlockEvent.model_validate_json(json.dumps(row["body"]))
        for row in store.list("benchmark_block_event", run.identity)
    ]


def _layout(slots):
    return [(slot["slot"], arm) for slot in slots for arm in slot["order"]]


def _state(events, slots, run_ref):
    layout = _layout(slots)
    captured = {}
    claim = None
    stop = None
    for seq, event in enumerate(events, 1):
        key = (event.slot, event.arm)
        if (
            event.run != run_ref
            or event.version != seq
            or stop is not None
            or len(captured) >= len(layout)
            or key != layout[len(captured)]
        ):
            raise ValueError("block progress differs from the frozen allocation")
        if event.action == "claim" and claim is None and _safe(event.available_bytes):
            claim = event
        elif event.action == "capture" and claim is not None:
            if event.available_bytes is not None or event.report_id in captured.values():
                raise ValueError("block capture must pin one distinct evaluator report")
            captured[key] = event.report_id
            claim = None
        elif event.action == "memory_stop" and not _safe(event.available_bytes):
            stop = event
        else:
            raise ValueError("invalid block progress transition")
    return captured, claim, stop


def _verified_arm(store, run, protocol, slot, name, case, report_id):
    ref = store.reference(run)
    plan = _plan(store, run.pilot)
    return _arm_evidence(
        store,
        report_id,
        _context(ref, run, protocol, slot, name, local_mode=plan.mode),
        protocol,
        case,
        digest([ref.content_hash, slot["slot"]])[:32],
    )


def validate_event(store, event):
    run = store.get(event.run)
    _plan(store, run.pilot)
    if run.identity != _run_identity(run.pilot):
        raise ValueError("block run must have its unique plan-derived identity")
    protocol, _, slots, catalog = run_inputs(store, run)
    _state([*_events(store, run), event], slots, event.run)
    if event.action == "capture":
        slot = next(s for s in slots if s["slot"] == event.slot)
        _verified_arm(
            store, run, protocol, slot, event.arm, catalog[slot["scenario_id"]], event.report_id
        )


def _record(store, run, index, slot, arm, action, *, memory=None, report_id=None):
    store.append(
        BenchmarkBlockEvent(
            identity=run.identity,
            version=index,
            created_at=datetime.now(UTC),
            author=run.author,
            run=store.reference(run),
            slot=slot["slot"],
            arm=arm,
            action=action,
            available_bytes=memory,
            report_id=report_id,
        )
    )


async def _watch_trial(operation, probe):
    task = asyncio.create_task(operation)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=POLL_SECONDS)
            if done:
                return task.result(), None
            observed = _sample(probe)
            if not _safe(observed):
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return None, observed
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def execute_block(store, plan_ref, block, *, local_opt_in=False, transport=None, probe=None):
    """Run precisely one preregistered pair. Claims are consumed before creating a trial."""
    from agent_reliability_lab.research.ollama import (
        guard_database,
        open_local,
        validate_local_plan,
        verify_discovery_arm,
    )

    guard_database(store)
    plan = _plan(store, plan_ref)
    mocked = type(transport) is httpx2.MockTransport
    if not local_opt_in or (plan.mode == "ollama_mock") != mocked or (probe and not mocked):
        raise ValueError("explicit local opt-in and matching transport required")
    probe = probe or available_memory
    validate_local_plan(store, plan, plan.protocol)
    protocol = store.get(plan.protocol)
    slots, catalog = schedule(store.get(protocol.dataset), protocol)
    if type(block) is not int or not 1 <= block <= len(slots):
        raise ValueError("block is outside the frozen allocation")
    observed = provenance(
        ExperimentConfig(
            experimental_evaluator=protocol.evaluator_version, source_method=protocol.source_method
        )
    )
    if observed["working_tree_dirty"] or not _source_matches(protocol, observed):
        raise ValueError("block execution requires matching clean source and lock")
    run = _read_run(store, plan_ref)
    if run is None and block != 1:
        raise ValueError("prior blocks must complete before this block")
    if run is None:
        run = BenchmarkRun(
            identity=_run_identity(plan_ref),
            author=protocol.author,
            created_at=datetime.now(UTC),
            protocol=plan.protocol,
            schedule_hash=plan.schedule_hash,
            pilot=plan_ref,
        )
        store.append(run)
    ref = store.reference(run)
    events = _events(store, run)
    captured, active, stopped = _state(events, slots, ref)
    slot = slots[block - 1]
    if all((slot["slot"], name) in captured for name in slot["order"]):
        return {"status": "block_complete", "block": block, "run": ref.model_dump(mode="json")}
    if active is not None or stopped is not None:
        return {"status": "stopped", "block": block, "run": ref.model_dump(mode="json")}
    if len(captured) != (block - 1) * 2:
        raise ValueError("prior blocks must complete before this block")
    factory = None
    runner = ScenarioRunner(store.engine)
    case = catalog[slot["scenario_id"]]
    number = len(events) + 1
    with TemporaryDirectory(prefix="opsdesk-local-block-") as temporary:
        path = Path(temporary) / "case.json"
        path.write_text(case.case.model_dump_json(), encoding="utf-8")
        for arm in slot["order"]:
            memory = _sample(probe)
            if not _safe(memory):
                _record(store, run, number, slot, arm, "memory_stop", memory=memory)
                return {"status": "stopped", "block": block, "run": ref.model_dump(mode="json")}
            if factory is None:
                factory = await open_local(store, plan, plan.protocol, transport)
                memory = _sample(probe)
                if not _safe(memory):
                    _record(store, run, number, slot, arm, "memory_stop", memory=memory)
                    return {"status": "stopped", "block": block, "run": ref.model_dump(mode="json")}
            _record(store, run, number, slot, arm, "claim", memory=memory)
            number += 1
            model = factory(ref, slot["slot"], arm, protocol.model)
            trial_and_report, low = await _watch_trial(
                run_benchmark_arm(
                    runner,
                    path,
                    protocol,
                    case,
                    arm,
                    digest([ref.content_hash, slot["slot"]])[:32],
                    slot,
                    _context(ref, run, protocol, slot, arm, local_mode=plan.mode),
                    model,
                ),
                probe,
            )
            if trial_and_report is None:
                _record(store, run, number, slot, arm, "memory_stop", memory=low)
                return {"status": "stopped", "block": block, "run": ref.model_dump(mode="json")}
            trial, frozen = trial_and_report
            score, _ = _verified_arm(store, run, protocol, slot, arm, case, frozen["report_id"])
            verify_discovery_arm(store, model, score, trial)
            _record(store, run, number, slot, arm, "capture", report_id=frozen["report_id"])
            number += 1
    return {"status": "block_complete", "block": block, "run": ref.model_dump(mode="json")}


def _persisted_arms(store, run):
    trial, exp, report = evaluation.trials, evaluation.experiments, evaluation.reports
    context = exp.c.manifest["benchmark"].label("context")
    query = (
        sa.select(
            trial.c.trial_id, trial.c.execution_id, trial.c.state, report.c.report_id, context
        )
        .select_from(trial.join(exp).outerjoin(report))
        .where(exp.c.manifest["benchmark"]["run"]["identity"].as_string() == run.identity)
    )
    with store.engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(query).mappings()]
    result = {}
    for row in rows:
        ctx = row["context"]
        key = (ctx["slot"]["slot"], ctx["arm"])
        if key in result:
            raise ValueError("multiple persisted trials or reports for one claimed arm")
        result[key] = row
    return result


def reconstruct_blocks(store, plan_ref):
    """Read-only, indexed by the immutable schedule, including all missing slots."""
    from agent_reliability_lab.research.ollama import guard_database

    guard_database(store)
    plan = _plan(store, plan_ref)
    protocol = store.get(plan.protocol)
    slots, catalog = schedule(store.get(protocol.dataset), protocol)
    run = _read_run(store, plan_ref)
    broker_events, progress, records, captured = [], [], {}, {}
    pending = stop = ref = present = None
    if run is not None:
        ref = store.reference(run)
        progress = _events(store, run)
        captured, pending, stop = _state(progress, slots, ref)
        records = _persisted_arms(store, run)
        with store.engine.connect() as conn:
            present = conn.scalar(
                sa.select(ledgers.c.ledger_id).where(ledgers.c.ledger_id == plan.ledger_id)
            )
        if present:
            broker_events = PilotBudgetBroker(store.engine, store.scope, plan).snapshot()
    latest = {item["attempt_id"]: item["body"] for item in broker_events}
    allocations = {(a.slot, a.arm): a.model_dump(mode="json") for a in validate_plan(store, plan)}
    pending_key = (pending.slot, pending.arm) if pending else None
    if set(records) - (set(captured) | {pending_key}):
        raise ValueError("a persisted trial exists without an allocation claim")
    pairs = []
    linked = set()
    for slot in slots:
        observations = {}
        for arm in slot["order"]:
            key = slot["slot"], arm
            row = records.get(key)
            item = {"state": "not_started"}
            if key in captured or key == pending_key:
                item["state"] = "claimed_without_checkpoint" if key == pending_key else "verified"
                if row is not None:
                    expected = _context(ref, run, protocol, slot, arm, local_mode=plan.mode)
                    if expected != row["context"]:
                        raise ValueError("persisted trial differs from claimed allocation")
                    item.update({name: row[name] for name in ("trial_id", "execution_id")})
                    attempts = {
                        attempt: details
                        for attempt, details in latest.items()
                        if details["request"]["execution_id"] == row["execution_id"]
                    }
                    if any(
                        d["request"]["allocation"] != allocations[key]
                        or d["request"]["authorization_hash"] != plan_ref.content_hash
                        or not d["request"]["wire_hash"]
                        for d in attempts.values()
                    ):
                        raise ValueError("broker request differs from its frozen arm")
                    linked.update(attempts)
                    item["attempt_ids"] = sorted(attempts)
                if key in captured:
                    if row is None or row["report_id"] != captured[key]:
                        raise ValueError("checkpointed evaluator report missing")
                    case = catalog[slot["scenario_id"]]
                    score, capture = _verified_arm(
                        store, run, protocol, slot, arm, case, captured[key]
                    )
                    evidence = store.evaluations.trial(row["trial_id"])["evidence"]
                    if evidence is None:
                        raise ValueError("checkpoint has no captured evidence")
                    _verify_request(evidence, attempts)
                    item["capture"] = capture
                    if diagnostic := task_recovery(case, evidence, score):
                        item["recovery_diagnostic"] = diagnostic
                elif row is not None and row["report_id"] is not None:
                    _, frozen = _verified_arm(
                        store,
                        run,
                        protocol,
                        slot,
                        arm,
                        catalog[slot["scenario_id"]],
                        row["report_id"],
                    )
                    evidence = store.evaluations.trial(row["trial_id"])["evidence"]
                    if evidence is not None:
                        _verify_request(evidence, attempts)
                    item["uncheckpointed_capture"] = frozen
                elif row is not None and row["execution_id"]:
                    sealed = ExecutionStore(store.engine).provenance(row["execution_id"])
                    item["journal_hash"] = verify_provenance(sealed, row["execution_id"])
                    starts = {
                        rec["reference"]: rec["body"]
                        for rec in sealed
                        if rec["kind"] == "model_started"
                    }
                    if any(
                        attempt not in starts
                        or any(
                            details["request"][name] != starts[attempt][name]
                            for name in ("execution_id", "turn", "input_hash")
                        )
                        for attempt, details in attempts.items()
                    ):
                        raise ValueError("uncheckpointed request differs from its sealed input")
            observations[arm] = item
        comparison = "incomplete"
        if all(a["state"] == "verified" for a in observations.values()):
            comparison, _, _ = verify_pair(
                store.evaluations,
                observations["baseline"]["trial_id"],
                observations["guarded"]["trial_id"],
                protocol.dataset,
            )
        pairs.append({"allocation": slot, "arms": observations, "comparison": comparison})
    if linked != set(latest):
        raise ValueError("broker events lack a unique claimed execution")
    if run and _events(store, run) != progress:
        raise ValueError("block progress changed during reconstruction")
    if present and PilotBudgetBroker(store.engine, store.scope, plan).snapshot() != broker_events:
        raise ValueError("block broker evidence changed during reconstruction")
    return {
        "schema": "local_memory_blocks_v1",
        "plan": plan_ref.model_dump(mode="json"),
        "run": ref.model_dump(mode="json") if ref else None,
        "schedule_hash": plan.schedule_hash,
        "memory_floor_bytes": MEMORY_FLOOR,
        "block_size_pairs": 1,
        "status": "stopped"
        if stop
        else "interrupted_or_active"
        if pending
        else "complete"
        if len(captured) == len(slots) * 2
        else "between_blocks",
        "progress": [p.model_dump(mode="json") for p in progress],
        "pairs": pairs,
        "broker_event_hash": digest(broker_events),
        "broker_events": broker_events,
    }
