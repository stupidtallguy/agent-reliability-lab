import asyncio
import json
import uuid

import httpx2
import pytest
from sqlalchemy.exc import NoResultFound

from agent_reliability_lab.agent.errors import ModelFailure
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import execute_benchmark
from agent_reliability_lab.research.ollama import reconstruct, register
from agent_reliability_lab.research.ollama_model import TAG
from agent_reliability_lab.research.persistence import ResearchStore
from agent_reliability_lab.research.pilot import publish_pilot
from agent_reliability_lab.research.pilot_contracts import OllamaProfile

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "case",
    [
        "paired",
        "smoke",
        "timeout",
        "connection",
        "redirect",
        "invalid_json",
        "context",
        "unavailable",
        "changed",
        "unknown_tool",
        "wrong_arguments",
        "duplicate_call_id",
        "missing_usage",
        "denied",
        "guard_scope",
        "tampered",
        "cloud_tag",
        "no_tools",
    ],
)
def test_local_pipeline(manager, monkeypatch, case):
    async def deny(*args):
        pytest.fail("the offline test attempted a network request")

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", deny)
    monkeypatch.setenv("OPSDESK_TEST_OWNED", "1")
    store = ResearchStore(manager.engine, "cp20_" + uuid.uuid4().hex)
    asyncio.run(store.initialize())
    profile = OllamaProfile(
        model_digest="a" * 64,
        quantization="Q4_K_M",
        template_hash=digest("template"),
        hardware={"cpu": "fixture"},
        smoke=case not in {"paired", "guard_scope"},
    )
    ref = register(store, profile, mock=True)
    plan = store.get(ref)
    calls = []

    def handler(req):
        assert req.url.host == "127.0.0.1" and req.url.port == 11434
        if req.url.path == "/api/version":
            data = {"version": "0.40.16"}
        elif req.url.path == "/api/show":
            data = {
                "details": {"format": "gguf", "family": "qwen35", "quantization_level": "Q4_K_M"},
                "capabilities": ["tools"],
                "template": "template",
            }
            if case == "cloud_tag":
                data["remote_host"] = "https://example.invalid"
            if case == "no_tools":
                data["capabilities"] = ["completion"]
        elif req.url.path == "/api/tags":
            data = {
                "models": []
                if case == "unavailable"
                else [
                    {"name": TAG, "model": TAG, "digest": ("b" if case == "changed" else "a") * 64}
                ]
            }
        else:
            assert req.url.path == "/api/chat"
            wire = json.loads(req.content)
            assert (
                wire["model"] == TAG and wire["truncate"] is wire["shift"] is wire["think"] is False
            )
            assert wire["options"] == dict(num_ctx=4096, num_predict=256, temperature=0, seed=42)
            calls.append(digest(wire))
            if case == "timeout":
                raise httpx2.ReadTimeout("simulated")
            if case == "connection":
                raise httpx2.ReadError("interrupted")
            if case == "redirect":
                return httpx2.Response(307, headers={"location": "https://example.invalid"})
            if case == "invalid_json":
                return httpx2.Response(200, content=b"{")
            if case == "context":
                return httpx2.Response(400, json={"error": "context length exceeded"})
            tools = [m for m in wire["messages"] if m["role"] == "tool"]
            msg = {"role": "assistant", "content": "Order shipped."}
            if not tools:
                name = {"unknown_tool": "unlisted", "denied": "update_task"}.get(case, "get_order")
                args = {"order_id": "order_001"}
                if case in {"smoke", "missing_usage", "tampered"}:
                    name = "create_task"
                    args = {"customer_id": "customer_001", "title": "Shipment follow-up"}
                if case == "wrong_arguments":
                    args = {"unknown": False}
                if case == "guard_scope":
                    name = "update_task"
                    args = {
                        "task_id": "task_001",
                        "expected_version": 1,
                        "patch": {"title": "outside scope"},
                    }
                if case == "denied":
                    args = {"task_id": "task_other", "patch": {"status": "resolved"}}
                item = {"id": "fixture-call", "function": {"name": name, "arguments": args}}
                msg.update(
                    content="", tool_calls=[item, item] if case == "duplicate_call_id" else [item]
                )
            else:
                assert tools[0]["tool_name"] and tools[0]["tool_call_id"] == "fixture-call"
            data = dict(
                model=TAG, done=True, done_reason="stop", message=msg, eval_duration=27000000
            )
            if case != "missing_usage":
                data.update(prompt_eval_count=31, eval_count=7)
        return httpx2.Response(200, json=data)

    async def run():
        return await execute_benchmark(
            store,
            plan.protocol,
            pilot_ref=ref,
            local_opt_in=True,
            mock_transport=httpx2.MockTransport(handler),
        )

    if case in {"unavailable", "changed", "cloud_tag", "no_tools"}:
        with pytest.raises((ValueError, ModelFailure), match="unavailable|differs|unverified"):
            asyncio.run(run())
        assert not calls
        return
    run_ref, result = asyncio.run(run())
    receipt = {"plan": ref.model_dump(mode="json")}
    if case in {"paired", "guard_scope"}:
        receipt["report"] = publish_pilot(store, ref, run_ref).model_dump(mode="json")
        doc = reconstruct(store, receipt)
        assert doc["interpretation"] == "ollama_mock"
        assert all(p["comparison"] == "verified" for p in doc["benchmark"]["pairs"])
        assert doc["usage"]["physical_dispatches"] == 8
        assert doc["usage"]["reported_input_tokens"]["sum_observed"] == 8 * 31
        if case == "guard_scope":
            for pair in doc["benchmark"]["pairs"]:
                trial = store.evaluations.trial(pair["arms"]["guarded"]["trial_id"])
                assert not trial["evidence"]["audits"]
                assert any(e["event_type"] == "defense_block" for e in trial["evidence"]["events"])
        return
    receipt.update(run=run_ref.model_dump(mode="json"), report_id=result["report_id"])
    doc = reconstruct(store, receipt)
    evidence = doc["evidence"]
    assert evidence and doc["score"]["mode"] == "scripted"
    terminal = doc["provider_events"][-1]["body"]
    if case in {"connection", "timeout"}:
        assert terminal["state"] == "uncertain" and len(calls) == 1
        recovered = reconstruct(
            ResearchStore(manager.engine, store.scope), {"plan": receipt["plan"]}
        )
        assert recovered["status"] == "incomplete"
        assert recovered["provider_events"] == doc["provider_events"] and len(calls) == 1
    elif case in {"context", "invalid_json", "redirect", "duplicate_call_id"}:
        assert terminal["observation"]["outcome"] == "failed" and len(calls) == 1
    else:
        assert len(calls) == 2
        assert terminal["observation"]["ollama_duration_ns"]["eval_duration"] == 27000000
        if case == "smoke":
            assert len(evidence["audits"]) == 1
        if case == "missing_usage":
            assert terminal["observation"]["input_tokens"] is None
        if case in {"unknown_tool", "wrong_arguments", "denied"}:
            assert not evidence["audits"]
        if case == "tampered":
            original = store.evaluations.trial

            def altered(trial_id):
                trial = original(trial_id)
                trial["evidence"]["audits"].clear()
                return trial

            monkeypatch.setattr(store.evaluations, "trial", altered)
            with pytest.raises(ValueError):
                reconstruct(store, receipt)
        with pytest.raises(NoResultFound):
            reconstruct(store, receipt | {"report_id": "0" * 32})
