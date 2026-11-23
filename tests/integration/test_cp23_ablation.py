"""Offline HTTP controls for the complete PostgreSQL-backed factorial pathway."""

import asyncio
import json
import uuid

import httpx2
import pytest
from test_cp22_discovery import scripted_call

from agent_reliability_lab.adversarial.defenses import GUARDED_POLICY
from agent_reliability_lab.agent.graph import SYSTEM_POLICY
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import execute_benchmark, schedule
from agent_reliability_lab.research.ollama import ABLATION_PROFILE, register
from agent_reliability_lab.research.ollama_model import TAG
from agent_reliability_lab.research.persistence import ResearchStore
from agent_reliability_lab.research.pilot import publish_pilot, render_pilot, verify_pilot_report
from agent_reliability_lab.research.pilot_contracts import OllamaProfile

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("controls", [False, True])
def test_factorial_trials_preserve_core_controls(manager, monkeypatch, controls):
    async def deny(*args):
        pytest.fail("factorial fixture attempted real networking")

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", deny)
    monkeypatch.setenv("OPSDESK_TEST_OWNED", "1")
    store = ResearchStore(manager.engine, "cp23_" + uuid.uuid4().hex)
    asyncio.run(store.initialize())
    profile = OllamaProfile(
        version=ABLATION_PROFILE,
        model_digest="a" * 64,
        quantization="Q4_K_M",
        template_hash=digest("fixture"),
        hardware={},
    )
    plan_ref = register(store, profile, mock=True)
    plan = store.get(plan_ref)
    protocol = store.get(plan.protocol)
    slots, _ = schedule(store.get(protocol.dataset), protocol)
    allocation = [
        (slot["repetition"], slot["factors"][arm]) for slot in slots for arm in slot["order"]
    ]
    calls = []
    catalog_hashes = set()
    pre_write_inputs = {}
    trial_index = -1

    def response(request):
        nonlocal trial_index
        assert request.url.host == "127.0.0.1" and request.url.port == 11434
        path = request.url.path
        if path == "/api/tags":
            return httpx2.Response(
                200, json={"models": [{"name": TAG, "model": TAG, "digest": "a" * 64}]}
            )
        if path == "/api/show":
            return httpx2.Response(
                200,
                json={
                    "details": {
                        "format": "gguf",
                        "family": "qwen35",
                        "quantization_level": "Q4_K_M",
                    },
                    "capabilities": ["tools"],
                    "template": "fixture",
                },
            )
        if path == "/api/version":
            return httpx2.Response(200, json={"version": "0.40.16"})
        assert path == "/api/chat"
        wire = json.loads(request.content)
        messages = wire["messages"]
        observations = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if not observations:
            trial_index += 1
        repetition, factors = allocation[trial_index]
        system, framing, scope = (
            factors[k] for k in ("system_policy", "observation_framing", "task_scope_filter")
        )
        assert messages[0]["content"] == SYSTEM_POLICY + (GUARDED_POLICY if system else "")
        assert all(("observation_trust" in obs) == framing for obs in observations)
        catalog_hashes.add(digest(wire["tools"]))
        calls.append(digest(wire))
        selected = None
        if controls:
            selected = {
                (False, False): "intermediate",
                (False, True): "stale",
                (True, False): "malformed",
                (True, True): "foreign" if repetition == 1 else "duplicate",
            }[system, framing]
        call = scripted_call(messages, selected)
        message = {"role": "assistant", "content": "The mock finished its bounded operation."}
        if call:
            name, args = call
            if name == "update_task":
                if len(observations) == 4:
                    # Codes, call IDs and correlation IDs in previous turns are sandbox-specific.
                    normalized = [obs.get("observation", obs) for obs in observations]
                    key = (repetition, system, framing)
                    contract = (
                        messages[0]["content"],
                        messages[1]["content"],
                        normalized,
                        wire["tools"],
                    )
                    if key not in pre_write_inputs:
                        pre_write_inputs[key] = contract
                    else:
                        assert pre_write_inputs[key] == contract
                if selected == "intermediate":
                    args["patch"] = {"status": "in_progress"}
                if selected == "foreign":
                    args["task_id"] = "foreign_task"
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"fixture_{len(observations)}",
                        "function": {"name": name, "arguments": args},
                    }
                ],
            }
        return httpx2.Response(
            200,
            json=dict(
                model=TAG,
                done=True,
                done_reason="stop",
                message=message,
                prompt_eval_count=200,
                eval_count=20,
            ),
        )

    assert plan.limits.total_calls == 112
    result_ref, _ = asyncio.run(
        execute_benchmark(
            store,
            plan.protocol,
            pilot_ref=plan_ref,
            local_opt_in=True,
            mock_transport=httpx2.MockTransport(response),
        )
    )
    report = store.get(publish_pilot(store, plan_ref, result_ref))
    document = verify_pilot_report(store, report)
    assert render_pilot(document) == render_pilot(verify_pilot_report(store, report))
    benchmark = document["benchmark"]
    assert benchmark["summary"]["method"] == "factorial_cell_counts_v1"
    assert len(benchmark["summary"]["cells"]) == 8
    assert len(benchmark["pairs"]) == 8 and benchmark["materialized_trials"] == 16
    assert len(catalog_hashes) == 1
    for pair in benchmark["pairs"]:
        assert pair["comparison"] == "verified"
        for arm, record in pair["arms"].items():
            trial = store.evaluations.trial(record["trial_id"])
            evidence = trial["evidence"]
            factors = pair["factors"][arm]
            assert evidence["execution"]["config"]["defense"]["factors"] == factors
            scope = factors["task_scope_filter"]
            target = evidence["final"]["tasks"]["task_001"]
            if not controls:
                assert record["measurements"]["task_success"]["value"] is True
                assert target["status"] == "resolved" and target["version"] == 2
                assert len(evidence["receipts"]) == len(evidence["audits"]) == 1
                continue
            system = factors["system_policy"]
            framing = factors["observation_framing"]
            operation = evidence["operations"][-1]
            error = operation["response"]["error"]
            if not system and not framing and not scope:
                assert error is None and target["status"] == "in_progress"
                writes = 1
            elif system and framing and pair["repetition"] == 2:
                assert error["code"] == "version_conflict" and target["status"] == "resolved"
                writes = 1
            else:
                expected = (
                    "validation_error"
                    if system and not framing
                    else "version_conflict"
                    if not system and framing
                    else "task_scope_denied"
                    if scope
                    else "not_found"
                )
                assert error["code"] == expected
                assert target["status"] == "open"
                writes = 0
            assert record["measurements"]["attack_success"]["status"] == "not_applicable"
            assert len(evidence["receipts"]) == len(evidence["audits"]) == writes
    assert document["usage"]["physical_dispatches"] == len(calls)
