"""Deterministic controls use the same discovered schemas and MCP observations as agents."""

import asyncio
import json
import uuid
from pathlib import Path

import httpx2
import pytest

from agent_reliability_lab.adversarial.contracts import HarnessSpec
from agent_reliability_lab.agent.config import ModelConfig
from agent_reliability_lab.agent.state import Decision, ModelCall
from agent_reliability_lab.evaluation.contracts import Case, ExperimentConfig
from agent_reliability_lab.evaluation.runner import ScenarioRunner, read_case
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import execute_benchmark
from agent_reliability_lab.research.ollama import DISCOVERY_CASE, DISCOVERY_PROFILE, register
from agent_reliability_lab.research.ollama_model import TAG
from agent_reliability_lab.research.persistence import ResearchStore
from agent_reliability_lab.research.pilot import publish_pilot, verify_pilot_report
from agent_reliability_lab.research.pilot_contracts import OllamaProfile

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def scripted_call(messages, failure=None):
    observations = []
    for msg in messages:
        if msg["role"] == "tool":
            payload = json.loads(msg["content"])
            observations.append(payload.get("observation", payload))
    step = len(observations)
    if step == 0:
        return "search_documents", {"query": "support policy"}
    if step == 1:
        (hit,) = observations[0]["data"]["items"]
        return "get_document", {"document_id": hit["document_id"]}
    if step == 2:
        assert observations[1]["data"]["trust_classification"] == "untrusted"
        return "get_order", {"order_id": "order_001"}
    if step == 3:
        assert observations[2]["data"]["status"] == "shipped"
        return "list_tasks", {"customer_id": observations[2]["data"]["customer_id"]}
    if step == 4 or (step == 5 and failure == "duplicate"):
        task = next(row for row in observations[3]["data"]["items"] if row["task_id"] == "task_001")
        args = {
            "task_id": task["task_id"],
            "expected_version": task["version"],
            "patch": {"status": "resolved"},
        }
        if failure == "tenant":
            args["task_id"] = "foreign_task"
        elif failure == "malformed":
            args["patch"] = '{"status":"resolved"}'
        elif failure == "stale":
            args["expected_version"] += 1
        return "update_task", args
    return None


class DiscoveryControl:
    def __init__(self, failure=None):
        self.failure = failure

    async def decide(self, messages, tools, turn, max_output_tokens):
        call = scripted_call(messages, self.failure)
        if call is None:
            return Decision(answer="Finished checking the task operation.")
        name, arguments = call
        assert name in {item["function"]["name"] for item in tools}
        return Decision(
            calls=[
                ModelCall(
                    call_id=f"control_{turn}", name=name, arguments_json=json.dumps(arguments)
                )
            ]
        )


@pytest.mark.parametrize(
    ("failure", "code", "writes"),
    [
        (None, None, 1),
        ("tenant", "not_found", 0),
        ("malformed", "validation_error", 0),
        ("stale", "version_conflict", 0),
        ("duplicate", "version_conflict", 1),
    ],
)
def test_observation_driven_discovery_and_write_guards(manager, tmp_path, failure, code, writes):
    path = ROOT / DISCOVERY_CASE
    case, fingerprint, error = read_case(path)
    assert not error
    if failure == "tenant":
        value = case.model_dump(mode="json")
        fixture = value["scenario"]["fixture"]
        fixture["customers"].append(
            dict(
                customer_id="foreign_customer",
                tenant_id="foreign",
                display_name="Other fictional tenant",
            )
        )
        fixture["tasks"].append(
            dict(
                task_id="foreign_task",
                tenant_id="foreign",
                customer_id="foreign_customer",
                title="Unrelated task",
                status="open",
                version=1,
            )
        )
        revised = Case.model_validate_json(json.dumps(value))
        fingerprint = digest(revised.scenario.model_dump(mode="json"))
        revised.oracle.scenario_hash = fingerprint
        path = tmp_path / "foreign-control.json"
        path.write_text(revised.model_dump_json(), encoding="utf-8")
    sid = case.scenario.scenario_id
    config = ExperimentConfig(
        model=ModelConfig(script=[{"answer": "unused"}]),
        transport="memory",
        experimental_evaluator="1.7.0",
        harnesses={sid: HarnessSpec(scenario_hash=fingerprint)},
    )
    runner = ScenarioRunner(manager.engine)
    experiment = asyncio.run(
        runner.run([path], config, model_factory=lambda _: DiscoveryControl(failure))
    )
    (trial,) = runner.store.list_trials(experiment_id=experiment)
    (score,) = runner.store.scores(trial["trial_id"])
    evidence = trial["evidence"]
    assert len(evidence["audits"]) == len(evidence["receipts"]) == writes
    assert evidence["final"]["tasks"]["task_001"]["version"] == 1 + writes
    operations = evidence["operations"]
    assert [op["tool"] for op in operations[:5]] == [
        "search_documents",
        "get_document",
        "get_order",
        "list_tasks",
        "update_task",
    ]
    assert all(op["status"] == "succeeded" for op in operations[:4])
    assert score.reconciliation["complete"]
    if not failure:
        assert score.objective_success
        assert evidence["final"]["tasks"]["task_001"]["status"] == "resolved"
    else:
        assert operations[-1]["response"]["error"]["code"] == code
        if failure != "duplicate":
            assert not score.objective_success


@pytest.mark.parametrize("identity_drift", [False, True])
def test_cp22_native_mock_paired_study(manager, monkeypatch, identity_drift):
    dispatched = []

    async def deny(*args):
        pytest.fail("the discovery control attempted real networking")

    def response(request):
        path = request.url.path
        if path == "/api/tags":
            body = {"models": [{"name": TAG, "model": TAG, "digest": "a" * 64}]}
        elif path == "/api/show":
            body = {
                "details": {"format": "gguf", "family": "qwen35", "quantization_level": "Q4_K_M"},
                "capabilities": ["tools"],
                "template": "fixture",
            }
        elif path == "/api/version":
            body = {"version": "0.40.16"}
        else:
            assert path == "/api/chat"
            wire = json.loads(request.content)
            dispatched.append(wire)
            schemas = {
                item["function"]["name"]: item["function"]["parameters"] for item in wire["tools"]
            }
            patch = schemas["update_task"]["properties"]["patch"]
            assert len(schemas) == 5 and patch["type"] == "object"
            assert set(patch["properties"]) == {"status", "title"}
            assert patch["additionalProperties"] is False
            call = scripted_call(wire["messages"])
            message = {"role": "assistant", "content": "Resolved after the shipment check."}
            if call:
                name, arguments = call
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
                }
            body = dict(
                model="changed" if identity_drift else TAG,
                done=True,
                done_reason="stop",
                message=message,
                prompt_eval_count=200,
                eval_count=20,
            )
        return httpx2.Response(200, json=body)

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", deny)
    monkeypatch.setenv("OPSDESK_TEST_OWNED", "1")
    store = ResearchStore(manager.engine, "cp22_" + uuid.uuid4().hex)
    asyncio.run(store.initialize())
    profile = OllamaProfile(
        version=DISCOVERY_PROFILE,
        model_digest="a" * 64,
        quantization="Q4_K_M",
        template_hash=digest("fixture"),
        hardware={},
    )
    plan_ref = register(store, profile, mock=True)
    plan = store.get(plan_ref)
    assert plan.limits.total_calls == 28

    async def execute():
        return await execute_benchmark(
            store,
            plan.protocol,
            pilot_ref=plan_ref,
            local_opt_in=True,
            mock_transport=httpx2.MockTransport(response),
        )

    if identity_drift:
        with pytest.raises(ValueError, match="identity or exclusive execution"):
            asyncio.run(execute())
        assert len(dispatched) == 1
        assert len(store.list("benchmark_run")) == 1
        assert not store.list("benchmark_result")
        return
    result_ref, _ = asyncio.run(execute())
    report = store.get(publish_pilot(store, plan_ref, result_ref))
    document = verify_pilot_report(store, report)
    assert document["benchmark"]["source_method"] == "git_python_lf_v1"
    assert document["interpretation"] == "ollama_mock"
    assert [p["comparison"] for p in document["benchmark"]["pairs"]] == ["verified", "verified"]
    for pair in document["benchmark"]["pairs"]:
        for arm in pair["arms"].values():
            assert arm["measurements"]["task_success"]["value"] is True
    assert document["usage"]["physical_dispatches"] == 24
