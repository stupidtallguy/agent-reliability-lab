"""Exercise the memory stop and restart paths without a real provider."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx2
import pytest
import sqlalchemy as sa
from test_cp25_expanded import control, native_reply, scripted_control

from agent_reliability_lab.evaluation import tables as evaluation
from agent_reliability_lab.opsdesk.database import engine_from_env
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research import local_blocks
from agent_reliability_lab.research.benchmark import execute_benchmark
from agent_reliability_lab.research.contracts import Reference
from agent_reliability_lab.research.multifamily import reviewed_dataset
from agent_reliability_lab.research.ollama import BLOCK_PROFILE, register
from agent_reliability_lab.research.ollama_model import TAG
from agent_reliability_lab.research.persistence import ResearchStore, artifacts
from agent_reliability_lab.research.pilot_contracts import OllamaProfile

pytestmark = pytest.mark.integration
FLOOR = local_blocks.MEMORY_FLOOR


def ample():
    return 2 * FLOOR


def mock_ollama(on_dispatch=None):
    previous = {c.scenario_id: c for c in reviewed_dataset(expanded=True).cases}
    cases = {c.case.scenario.user_request: c for c in reviewed_dataset(blocks=True).cases}

    async def handle(request):
        assert request.url.host == "127.0.0.1" and request.url.port == 11434
        if request.url.path == "/api/tags":
            body = {"models": [{"name": TAG, "model": TAG, "digest": "a" * 64}]}
        elif request.url.path == "/api/show":
            body = {
                "details": {"format": "gguf", "family": "qwen35", "quantization_level": "Q4_K_M"},
                "capabilities": ["tools"],
                "template": "cp26-fixture",
            }
        elif request.url.path == "/api/version":
            body = {"version": "0.40.16"}
        else:
            assert request.url.path == "/api/chat"
            if on_dispatch is not None:
                await on_dispatch()
            wire = json.loads(request.content)
            assert wire["truncate"] is wire["shift"] is wire["think"] is False
            case = cases[wire["messages"][1]["content"]]
            spec = previous[case.scenario_id.replace("cp26_", "cp25_")]
            reply = control(spec, wire["messages"])
            body = dict(
                model=TAG,
                done=True,
                done_reason="stop",
                message=native_reply(reply),
                prompt_eval_count=180,
                eval_count=20,
            )
        return httpx2.Response(200, json=body)

    return httpx2.MockTransport(handle)


@pytest.fixture
def plan(manager, monkeypatch):
    async def deny(*args):
        pytest.fail("CP26 controls must never use a network model transport")

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", deny)
    monkeypatch.setenv("OPSDESK_TEST_OWNED", "1")
    store = ResearchStore(manager.engine, "cp26_" + uuid.uuid4().hex)
    asyncio.run(store.initialize())
    ref = register(
        store,
        OllamaProfile(
            version=BLOCK_PROFILE,
            model_digest="a" * 64,
            quantization="Q4_K_M",
            template_hash=digest("cp26-fixture"),
            hardware={},
        ),
        mock=True,
    )
    try:
        yield store, ref
    finally:
        # These tests deliberately retain interrupted sandboxes. Dispose only
        # the owned fixtures of this exact disposable plan after assertions.
        frozen_run = local_blocks._read_run(store, ref)
        if frozen_run:
            for row in local_blocks._persisted_arms(store, frozen_run).values():
                trial = store.evaluations.trial(row["trial_id"])
                owned = trial["sandbox_run_id"]
                if owned and trial["cleanup"]["status"] != "cleaned":
                    assert trial["ownership_marker"] and owned.startswith("eval_")
                    manager.cleanup(owned, expected_marker=trial["ownership_marker"])


def run(store, ref, block=1, *, probe=ample, transport=None):
    return asyncio.run(
        local_blocks.execute_block(
            store,
            ref,
            block,
            probe=probe,
            transport=transport or mock_ollama(),
            local_opt_in=True,
        )
    )


def read(store, ref):
    readonly = ResearchStore(store.engine.execution_options(postgresql_readonly=True), store.scope)
    return local_blocks.reconstruct_blocks(readonly, ref)


def test_whole_allocation_restart_and_idempotent_block(plan, monkeypatch):
    store, ref = plan
    virgin = read(store, ref)
    assert virgin["status"] == "between_blocks" and len(virgin["pairs"]) == 8
    assert virgin["memory_floor_bytes"] == 512 * 1024 * 1024
    with pytest.raises(ValueError, match="prior blocks"):
        run(store, ref, 2)
    assert run(store, ref)["status"] == "block_complete"
    first = read(store, ref)
    assert first["status"] == "between_blocks"
    assert first["pairs"][0]["comparison"] == "verified"
    assert all(pair["comparison"] == "incomplete" for pair in first["pairs"][1:])

    async def no_dispatch():
        pytest.fail("repeated block must not dispatch again")

    assert run(store, ref, transport=mock_ollama(no_dispatch))["status"] == "block_complete"
    assert read(store, ref) == first
    monkeypatch.setenv(
        "OPSDESK_DATABASE_URL", store.engine.url.render_as_string(hide_password=False)
    )
    child_block = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "block",
            store.scope,
            ref.model_dump_json(),
            "2",
        ],
        check=True,
        timeout=90,
        capture_output=True,
        text=True,
    )
    assert json.loads(child_block.stdout)["status"] == "block_complete"
    # Verify remaining boundaries with a fresh connection pool for each invocation.
    for block in range(3, 9):
        engine = sa.create_engine(store.engine.url)
        try:
            restarted = ResearchStore(engine, store.scope)
            assert run(restarted, ref, block)["status"] == "block_complete"
        finally:
            engine.dispose()
    settled = read(store, ref)
    assert settled["status"] == "complete"
    assert settled["schedule_hash"] == virgin["schedule_hash"]
    assert len(settled["progress"]) == 32
    assert all(p["comparison"] == "verified" for p in settled["pairs"])
    captures = [a["capture"] for p in settled["pairs"] for a in p["arms"].values()]
    assert len({c["report_id"] for c in captures}) == len(captures) == 16
    assert all(
        c["score_revision"] == 1 and c["measurements"]["task_success"]["value"] for c in captures
    )
    for p in settled["pairs"]:
        name = p["allocation"]["scenario_id"]
        for a in p["arms"].values():
            t = store.evaluations.trial(a["trial_id"])
            e = t["evidence"]
            expected = int("archive_policy" not in name)
            assert len(e["audits"]) == len(e["receipts"]) == expected
            assert t["cleanup"]["status"] == "cleaned"
            if name == "cp26_archive_policy":
                assert (
                    store.evaluations.scores(a["trial_id"])[0].experimental[
                        "verified_attack_exposure"
                    ]
                    is True
                )
            if "requery_inventory" in name:
                d = a["recovery_diagnostic"]
                assert d["information_recovered"] and d["model_corrective_write"]
                assert d["task_completed"] and d["transport_recovered"] is None
    assert read(store, ref) == settled


def test_low_or_unavailable_memory_before_claim(plan):
    store, ref = plan
    assert run(store, ref, probe=lambda: FLOOR - 1)["status"] == "stopped"
    d = read(store, ref)
    assert not d["broker_events"]
    assert [(p["action"], p["available_bytes"]) for p in d["progress"]] == [
        ("memory_stop", FLOOR - 1)
    ]
    assert run(store, ref, 1)["status"] == "stopped"
    assert read(store, ref) == d
    assert all(a["state"] == "not_started" for p in d["pairs"] for a in p["arms"].values())


def test_memory_pressure_between_arms_preserves_the_completed_score(plan):
    store, ref = plan

    def probe():
        return (
            0
            if any(r["body"]["action"] == "capture" for r in store.list("benchmark_block_event"))
            else FLOOR
        )

    assert run(store, ref, probe=probe)["status"] == "stopped"
    d = read(store, ref)
    assert [p["action"] for p in d["progress"]] == ["claim", "capture", "memory_stop"]
    assert d["pairs"][0]["comparison"] == "incomplete"
    assert sorted(a["state"] for a in d["pairs"][0]["arms"].values()) == ["not_started", "verified"]
    assert run(store, ref, 2)["status"] == "stopped"
    assert read(store, ref) == d


def test_memory_pressure_with_inflight_request_keeps_it_unscored(plan, monkeypatch):
    store, ref = plan
    monkeypatch.setattr(local_blocks, "POLL_SECONDS", 0.03)
    entered = False

    async def hold():
        nonlocal entered
        entered = True
        await asyncio.sleep(30)

    assert (
        run(store, ref, probe=lambda: 0 if entered else FLOOR, transport=mock_ollama(hold))[
            "status"
        ]
        == "stopped"
    )
    d = read(store, ref)
    assert [p["action"] for p in d["progress"]] == ["claim", "memory_stop"]
    (pending,) = [
        a for a in d["pairs"][0]["arms"].values() if a["state"] == "claimed_without_checkpoint"
    ]
    assert store.evaluations.scores(pending["trial_id"]) == []
    assert pending["journal_hash"]
    assert [e["kind"] for e in d["broker_events"]] == ["reserved", "dispatched", "uncertain"]
    assert d["broker_events"][-1]["body"]["observation"] is None
    assert run(store, ref)["status"] == "stopped"
    assert read(store, ref) == d


def child(action, scope, json_ref, block=None):
    engine = engine_from_env()
    try:
        store = ResearchStore(engine, scope)
        ref = Reference.model_validate_json(json_ref)
        if action == "crash":

            async def terminate():
                os._exit(73)

            run(store, ref, transport=mock_ollama(terminate))
            raise AssertionError("mock dispatch never reached the hard crash")
        if action == "block":
            print(json.dumps(run(store, ref, int(block)), sort_keys=True))
        else:
            assert action == "inspect"
            print(json.dumps(read(store, ref), sort_keys=True))
    finally:
        engine.dispose()


def test_process_loss_then_read_only_restart(plan, monkeypatch):
    store, ref = plan
    monkeypatch.setenv(
        "OPSDESK_DATABASE_URL", store.engine.url.render_as_string(hide_password=False)
    )
    command = [sys.executable, str(Path(__file__).resolve())]
    stopped = subprocess.run(
        [*command, "crash", store.scope, ref.model_dump_json()],
        check=False,
        timeout=90,
        capture_output=True,
        text=True,
    )
    assert stopped.returncode == 73, stopped.stderr
    verified = subprocess.run(
        [*command, "inspect", store.scope, ref.model_dump_json()],
        check=True,
        timeout=90,
        capture_output=True,
        text=True,
    )
    d = json.loads(verified.stdout)
    assert d == read(store, ref)
    assert d["status"] == "interrupted_or_active"
    assert [p["action"] for p in d["progress"]] == ["claim"]
    assert [e["kind"] for e in d["broker_events"]] == ["reserved", "dispatched"]
    assert run(store, ref)["status"] == "stopped"
    assert read(store, ref) == d


def test_source_mismatch_and_legacy_one_shot_denied(plan, monkeypatch):
    store, ref = plan
    protocol = store.get(ref).protocol
    with pytest.raises(ValueError, match="preregistered"):
        asyncio.run(
            execute_benchmark(
                store, protocol, pilot_ref=ref, local_opt_in=True, mock_transport=mock_ollama()
            )
        )
    base = local_blocks.provenance
    monkeypatch.setattr(
        local_blocks, "provenance", lambda config: base(config) | {"source_hash": "0" * 64}
    )
    with pytest.raises(ValueError, match="matching clean source"):
        run(store, ref)
    assert not store.list("benchmark_run")


def test_allocation_and_progress_are_immutable(plan):
    store, ref = plan
    assert run(store, ref, probe=lambda: None)["status"] == "stopped"
    for name in ("benchmark_pilot_plan", "benchmark_block_event"):
        with pytest.raises(sa.exc.DBAPIError), store.engine.begin() as c:
            c.execute(
                artifacts.update()
                .where(artifacts.c.scope == store.scope, artifacts.c.kind == name)
                .values(body={})
            )
    assert read(store, ref)["progress"][0]["available_bytes"] is None
    with store.engine.connect() as c:
        assert (
            c.scalar(
                sa.select(sa.func.count())
                .select_from(evaluation.scores)
                .join(evaluation.trials)
                .join(evaluation.experiments)
                .where(
                    evaluation.experiments.c.manifest["benchmark"]["run"]["identity"].as_string()
                    == local_blocks._run_identity(ref)
                )
            )
            == 0
        )


def test_archive_v2_requires_full_read_and_correct_answer(plan, manager, tmp_path):
    _, _ = plan
    spec = next(
        c for c in reviewed_dataset(blocks=True).cases if c.scenario_id == "cp26_archive_policy"
    )
    v1 = next(
        c for c in reviewed_dataset(expanded=True).cases if c.scenario_id == "cp25_archive_policy"
    )
    assert "read the full policy document" in spec.case.scenario.user_request
    assert "read the full policy document" not in v1.case.scenario.user_request
    assert spec.case.oracle.annotation_version == "2.0.0"
    assert spec.scenario_hash != v1.scenario_hash

    def snippet(messages, turn):
        if turn == 0:
            return "search_documents", {"query": "Pine archive access policy"}
        return "An archive pass is required and access must be recorded in the entry log."

    e, score = scripted_control(manager, tmp_path, spec, snippet)
    assert score.objective_success is False
    assert score.experimental["verified_attack_exposure"] is False
    assert not e["audits"]


def test_explicit_title_v2_rejects_the_observed_extra_word(plan, manager, tmp_path):
    _, _ = plan
    spec = next(
        c for c in reviewed_dataset(blocks=True).cases if c.scenario_id == "cp26_cancelled_order"
    )
    assert "“Review Lark cancellation”" in spec.case.scenario.user_request

    def wrong_title(messages, turn):
        if turn == 0:
            return "create_task", {
                "customer_id": "customer_lark",
                "title": "Review Lark cancellation only",
            }
        return "The out-of-scope write was rejected."

    e, score = scripted_control(manager, tmp_path, spec, wrong_title)
    assert score.objective_success is False and not e["audits"]
    assert e["operations"][0]["response"]["error"]["code"] == "task_scope_denied"


if __name__ == "__main__":
    child(*sys.argv[1:])
