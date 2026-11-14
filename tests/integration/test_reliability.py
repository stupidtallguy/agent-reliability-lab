"""Real PostgreSQL and MCP coverage for the synthetic side-effect boundary."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import sqlalchemy as sa
from mcp import Client
from pydantic import SecretStr

from agent_reliability_lab.mcp.client import TrustedClient
from agent_reliability_lab.mcp.context import BoundContext, LaunchConfig, LogicalOperation
from agent_reliability_lab.mcp.servers import create_server
from agent_reliability_lab.opsdesk.contracts import ActorContext, ServiceError
from agent_reliability_lab.opsdesk.fixtures import baseline_access, load_baseline
from agent_reliability_lab.reliability.notifications import (
    TOOL,
    NotificationLab,
    NotificationRequest,
    intents,
    outbox,
    provider,
)

pytestmark = pytest.mark.integration
ACTOR = ActorContext(actor_id="support_001", tenant_id="opsdesk")
PAYLOAD = {"customer_id": "customer_001", "template": "order_status"}


@pytest.fixture
def lab(manager):
    run = "rel_" + uuid.uuid4().hex[:18]
    sandbox = manager.provision(run, load_baseline(), baseline_access())
    with sandbox.transaction() as (_, registry):
        marker = registry["marker"]
    lab = NotificationLab(sandbox)
    lab.register(ACTOR)
    yield lab
    manager.cleanup(run, expected_marker=marker)


def queue(lab):
    return lab.queue(
        ACTOR, NotificationRequest(**PAYLOAD, idempotency_key="mcp_" + "a" * 64)
    ).notification_id


@pytest.mark.parametrize(
    ("fault", "callback", "expected_provider", "outcome"),
    [
        ("normal", "delivered", "accepted", "delivered"),
        ("normal", None, "accepted", "unknown"),
        ("normal", "failed", "accepted", "failed"),
        ("reject", None, "rejected", "provider_rejected"),
        ("timeout_before_accept", None, "submitted", "unknown"),
        ("lose_ack", None, "accepted", "unknown"),
    ],
)
def test_provider_outcomes(lab, fault, callback, expected_provider, outcome):
    identity = queue(lab)
    assert lab.evidence(identity)["outbox"] == "pending"
    lab.dispatch(identity, fault)
    if callback:
        lab.callback(identity, "terminal", 2, callback)
    evidence = lab.evidence(identity)
    assert (evidence["provider"], evidence["delivery"]) == (expected_provider, outcome)
    assert evidence["acknowledged"] is (fault in {"normal", "reject"})


def test_duplicate_provider_requests_and_conflicting_payload(lab):
    identity = queue(lab)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert set(pool.map(lambda _: lab.dispatch(identity), range(4))) == {"accepted"}
    with pytest.raises(ServiceError) as error:
        lab.dispatch(identity, payload_hash="different")
    assert error.value.detail.code == "idempotency_conflict"
    with lab.sandbox.transaction() as (connection, _):
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(provider)
                .where(provider.c.notification_id == identity)
            )
            == 1
        )
    assert [row["sequence"] for row in lab.evidence(identity)["provider_attempts"]] == [1, 2, 3, 4]


def test_duplicate_and_out_of_order_callbacks_never_undo_delivery(lab):
    identity = queue(lab)
    lab.dispatch(identity)
    lab.callback(identity, "terminal", 2, "delivered")
    lab.callback(identity, "terminal", 2, "delivered")
    lab.callback(identity, "older", 1, "pending")
    result = lab.evidence(identity)
    assert result["delivery"] == "delivered"
    assert [r["event_id"] for r in result["delivery_events"]] == ["older", "terminal"]
    with pytest.raises(ValueError, match="conflicting delivery callback"):
        lab.callback(identity, "terminal", 2, "failed")
    lab.callback(identity, "contradictory", 3, "failed")
    assert lab.evidence(identity)["delivery"] == "contradictory"


def test_dispatcher_restart_recovers_lost_ack_and_delayed_delivery(lab):
    identity = queue(lab)

    def crash():
        raise InterruptedError("stop the worker after provider commit")

    with pytest.raises(InterruptedError):
        lab.dispatch(identity, after_provider_commit=crash)
    restarted = NotificationLab(lab.sandbox)
    assert restarted.evidence(identity)["outbox"] == "pending"
    assert restarted.evidence(identity)["provider"] == "accepted"
    assert restarted.dispatch(identity) == "accepted"
    assert restarted.evidence(identity)["delivery"] == "unknown"
    restarted.callback(identity, "later", 1, "delivered")
    assert restarted.evidence(identity)["delivery"] == "delivered"


@pytest.mark.anyio
async def test_mcp_signed_retry_and_authorization(lab, manager):
    configuration = LaunchConfig(
        run_id=lab.sandbox.run_id,
        actor_id=ACTOR.actor_id,
        tenant_id=ACTOR.tenant_id,
        signing_key=SecretStr("9" * 64),
    )
    operation = LogicalOperation.new()
    binding = BoundContext.bind(manager.engine, configuration)
    async with Client(create_server("notifications", binding), cache=None) as sdk:
        client = TrustedClient(sdk, configuration)
        assert (await client.discover()).tools[0].name == TOOL
        unsigned = await sdk.call_tool(TOOL, PAYLOAD)
        assert unsigned.structured_content["error"]["code"] == "permission_denied"
        first = (await client.write(TOOL, PAYLOAD, operation)).structured_content
        retry = (await client.write(TOOL, PAYLOAD, operation)).structured_content
        conflict = await client.write(TOOL, {**PAYLOAD, "template": "support_update"}, operation)
        assert first["data"] == retry["data"]
        assert conflict.structured_content["error"]["code"] == "idempotency_conflict"
    viewer = configuration.model_copy(update={"actor_id": "viewer_001"})
    binding = BoundContext.bind(manager.engine, viewer)
    async with Client(create_server("notifications", binding), cache=None) as sdk:
        denied = await TrustedClient(sdk, viewer).write(TOOL, PAYLOAD, operation)
        assert denied.structured_content["error"]["code"] == "permission_denied"
    identifier = first["data"]["notification_id"]
    with lab.sandbox.transaction() as (connection, _):
        for table in (intents, outbox):
            assert (
                connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(table)
                    .where(table.c.notification_id == identifier)
                )
                == 1
            )


@pytest.mark.anyio
@pytest.mark.parametrize("transport", ["memory", "stdio"])
async def test_real_agent_retries_and_later_evidence_appends(manager, tmp_path, transport):
    import json

    from agent_reliability_lab.reliability.demo import prepare_reliability_demo
    from agent_reliability_lab.reliability.notifications import reports
    from agent_reliability_lab.research.views import ResearchView

    summary = await prepare_reliability_demo(manager.engine, tmp_path, transport=transport)
    try:
        assert summary["physical_tool_attempts"] == 2
        assert summary["local_mutations"] == summary["receipt_count"] == 1
        assert summary["revisions"][0]["delivery"] == "unknown"
        assert summary["revisions"][1]["delivery"] == "delivered"
        first, second = ResearchView(manager.engine).reliability_reports(summary["execution_id"])
        assert first["report_id"] == second["previous_report_id"]
        assert [a["status"] for a in first["retry"]["attempts"]] == ["failed", "succeeded"]
        assert first["retry"]["context_comparisons"][0]["relation"] == "changed"
        assert first["provider"]["delivery_events"] == []
        assert second["provider"]["delivery_events"][0]["status"] == "delivered"
        for revision in (first, second):
            exported = tmp_path / revision["report_id"] / "reliability.json"
            assert json.loads(exported.read_bytes()) == revision
        with (
            pytest.raises(sa.exc.ProgrammingError, match="append-only"),
            manager.engine.begin() as connection,
        ):
            connection.execute(
                reports.update()
                .where(reports.c.report_id == first["report_id"])
                .values(document=second)
            )
    finally:
        manager.cleanup(summary["sandbox_run_id"])


@pytest.mark.anyio
async def test_changed_model_input_does_not_change_signed_write_intent(lab, manager):
    from agent_reliability_lab.agent import tables as agent
    from agent_reliability_lab.agent.config import AgentConfig, ModelConfig
    from agent_reliability_lab.agent.demo import call
    from agent_reliability_lab.agent.execution import AgentExecution
    from agent_reliability_lab.reliability.context import compare_requests

    config = AgentConfig(
        sandbox_run_id=lab.sandbox.run_id,
        **ACTOR.model_dump(),
        domains=["documents", "notifications"],
        transport="memory",
        model=ModelConfig(
            script=[
                call(TOOL, **PAYLOAD),
                call("get_document", document_id="task_policy"),
                {"answer": "Synthetic workflow ended."},
            ]
        ),
    )
    execution = AgentExecution(manager.engine)
    identifier = await execution.create(
        "Record a synthetic notification and read a policy.", config
    )
    assert (await execution.run(identifier, config)).status == "completed"
    records = execution.store.provenance(identifier)
    requests = [row["reference"] for row in records if row["kind"] == "model_started"]
    comparison = compare_requests(records, identifier, requests[0], requests[-1])
    assert comparison["relation"] == "changed"
    assert comparison["observations"]["current"][-1]["documents"][0]["document_id"] == "task_policy"
    with manager.engine.connect() as connection:
        original = (
            connection.execute(
                sa.select(agent.operations).where(
                    agent.operations.c.execution_id == identifier,
                    agent.operations.c.tool == TOOL,
                )
            )
            .mappings()
            .one()
        )
    host = execution.launch(config)
    binding = BoundContext.bind(manager.engine, host)
    async with Client(create_server("notifications", binding), cache=None) as sdk:
        client = TrustedClient(sdk, host)
        operation = LogicalOperation(operation_id=original["operation_id"])
        replay = await client.write(TOOL, PAYLOAD, operation)
        assert replay.structured_content["data"] == original["response"]["data"]
        conflict = await client.write(TOOL, {**PAYLOAD, "template": "support_update"}, operation)
        assert conflict.structured_content["error"]["code"] == "idempotency_conflict"
