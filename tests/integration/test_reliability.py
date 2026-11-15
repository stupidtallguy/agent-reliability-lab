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


@pytest.fixture(autouse=True)
def publication_identity(monkeypatch, tmp_path):
    from agent_reliability_lab.reliability.attestation import PRIVATE_FILE, TRUST_DIR, generate_key

    private = tmp_path / "signer"
    trust = tmp_path / "trust"
    generate_key(private, trust)
    monkeypatch.setenv(PRIVATE_FILE, str(private))
    monkeypatch.setenv(TRUST_DIR, str(trust))
    return private, trust


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


def deliver(lab, identifier, sequence, status):
    event = lab.issue_event(identifier, sequence, status)
    lab.callback(identifier, event, sequence, status)
    return event


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
        deliver(lab, identity, 2, callback)
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
    terminal = deliver(lab, identity, 2, "delivered")
    lab.callback(identity, terminal, 2, "delivered")
    older = deliver(lab, identity, 1, "pending")
    result = lab.evidence(identity)
    assert result["delivery"] == "delivered"
    assert [r["event_id"] for r in result["delivery_events"]] == [older, terminal]
    with pytest.raises(ValueError, match="conflicting delivery callback"):
        lab.callback(identity, terminal, 2, "failed")
    assert NotificationLab(lab.sandbox).evidence(identity)["delivery"] == "contradictory"
    deliver(lab, identity, 3, "failed")
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
    deliver(restarted, identity, 1, "delivered")
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
    assert len(lab.evidence(identifier)["rejected_conflicting_intents"]) == 1
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
    assert summary["physical_tool_attempts"] == 2
    assert summary["local_mutations"] == summary["receipt_count"] == 1
    assert summary["revisions"][0]["delivery"] == "unknown"
    assert summary["revisions"][1]["delivery"] == "delivered"
    first, second = ResearchView(manager.engine).reliability_reports(summary["execution_id"])
    assert first["report_id"] == second["previous_report_id"]
    assert [a["status"] for a in first["retry"]["attempts"]] == ["failed", "succeeded"]
    retry = first["retry"]["receipt_reuse_attempts"]
    assert [(item["attempt_id"], item["ordinal"]) for item in retry] == [
        (first["retry"]["attempts"][1]["attempt_id"], 2)
    ]
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
    with manager.engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.to_regnamespace("opsdesk_run_" + summary["sandbox_run_id"]))
            )
            is None
        )


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


def test_authoritative_callback_cross_notification_and_conflicting_sequence(lab):
    first = queue(lab)
    second = lab.queue(
        ACTOR, NotificationRequest(**PAYLOAD, idempotency_key="mcp_" + "b" * 64)
    ).notification_id
    for identifier in (first, second):
        lab.dispatch(identifier)
    event = lab.issue_event(first, 1, "delivered")
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: lab.callback(first, event, 1, "delivered"), range(6)))
    assert len(lab.evidence(first)["delivery_events"]) == 1
    with pytest.raises(ValueError, match="conflicting provider event sequence"):
        lab.issue_event(first, 1, "failed")
    with pytest.raises(ValueError, match="contradictory_callback_identity"):
        lab.callback(second, event, 1, "delivered")
    for identifier in (first, second):
        evidence = NotificationLab(lab.sandbox).evidence(identifier)
        assert evidence["delivery"] == "contradictory"
        assert evidence["callback_conflicts"]
    assert not lab.evidence(second)["delivery_events"]


def test_unknown_event_cannot_establish_delivery(lab):
    identifier = queue(lab)
    lab.dispatch(identifier)
    with pytest.raises(ValueError, match="missing_authoritative_callback"):
        lab.callback(identifier, "invented", 1, "delivered")
    assert lab.evidence(identifier)["delivery"] == "contradictory"


@pytest.mark.parametrize(
    ("name", "field", "reason"),
    [
        ("outbox", "payload_hash", "contradictory_outbox_payload"),
        ("provider", "payload_hash", "contradictory_provider_payload"),
        ("provider_bindings", "provider_operation_id", "contradictory_provider_operation"),
        ("intents", "operation_key", "contradictory_intent_identity"),
    ],
)
def test_persisted_tampering_blocks_dispatch_and_delivery(lab, name, field, reason):
    from agent_reliability_lab.reliability import notifications

    identifier = queue(lab)
    lab.dispatch(identifier)
    if name != "provider_bindings":
        deliver(lab, identifier, 1, "delivered")
    table = getattr(notifications, name)
    with lab.sandbox.transaction() as (connection, _):
        connection.execute(
            table.update()
            .where(table.c.notification_id == identifier)
            .values({field: uuid.uuid4().hex})
        )
    with pytest.raises(ValueError, match=reason):
        lab.dispatch(identifier)
    evidence = lab.evidence(identifier)
    assert (evidence["delivery"], evidence["integrity_issue"]) == ("contradictory", reason)


def test_missing_intent_outbox_or_provider_does_not_confirm_delivery(lab):
    identifier = queue(lab)
    with pytest.raises(ValueError, match="provider acceptance"):
        lab.issue_event(identifier, 1, "delivered")
    assert lab.evidence(identifier)["delivery"] == "unknown"
    with lab.sandbox.transaction() as (connection, _):
        connection.execute(outbox.delete().where(outbox.c.notification_id == identifier))
    with pytest.raises(ValueError, match="missing_outbox"):
        lab.dispatch(identifier)
    assert lab.evidence(identifier)["delivery"] == "unknown"
    assert lab.evidence("unknown-notification")["delivery"] == "unknown"


def test_callback_conflict_survives_a_fresh_process(lab):
    import subprocess
    import sys

    identifier = queue(lab)
    lab.dispatch(identifier)
    event = deliver(lab, identifier, 1, "delivered")
    with pytest.raises(ValueError, match="contradictory_callback_identity"):
        lab.callback(identifier, event, 1, "failed")
    probe = """
import sys
from agent_reliability_lab.opsdesk.database import SandboxManager, engine_from_env
from agent_reliability_lab.reliability.notifications import NotificationLab
box = SandboxManager(engine_from_env()).open(sys.argv[1])
evidence = NotificationLab(box).evidence(sys.argv[2])
assert evidence["delivery"] == "contradictory"
assert evidence["callback_conflicts"] and evidence["delivery_events"][0]["status"] == "delivered"
"""
    subprocess.run(
        [sys.executable, "-c", probe, lab.sandbox.run_id, identifier], check=True, timeout=30
    )


@pytest.mark.anyio
async def test_revision_ancestry_rejects_forged_or_concurrent_successors(manager, tmp_path):
    from agent_reliability_lab.opsdesk.fixtures import digest
    from agent_reliability_lab.reliability.demo import prepare_reliability_demo
    from agent_reliability_lab.reliability.notifications import reports
    from agent_reliability_lab.reliability.revisions import freeze
    from agent_reliability_lab.research.views import ResearchView

    result = await prepare_reliability_demo(manager.engine, tmp_path)
    view = ResearchView(manager.engine)
    identifier = result["execution_id"]
    first, second = view.reliability_reports(identifier)
    keep = (tmp_path / first["report_id"] / "reliability.json").read_bytes()
    assert freeze(manager.engine, second, 2) == second
    with pytest.raises(ValueError, match="revision conflict"):
        freeze(manager.engine, {**second, "purpose": "different"}, 2)
    for bad, revision in [
        ({**second, "previous_report_id": second["report_id"]}, 99),
        ({**second, "previous_report_id": "a" * 64}, 3),
        ({**second, "previous_report_id": first["report_id"]}, 3),
        ({**second, "execution_id": "e" * 32, "previous_report_id": None}, 1),
    ]:
        with pytest.raises(ValueError):
            freeze(manager.engine, bad, revision)

    def candidate(label):
        document = {**second, "previous_report_id": second["report_id"], "purpose": label}
        try:
            return freeze(manager.engine, document, 3)
        except ValueError as error:
            assert "revision conflict" in str(error)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = [r for r in pool.map(candidate, ["one", "two"]) if r]
    assert len(winners) == 1
    assert view.reliability_reports(identifier, limit=1) == [first]
    assert view.reliability_reports(identifier)[-1] == winners[0]
    from agent_reliability_lab.reliability.metrics import render

    assert render(first, "json").encode() == keep
    forged = {**winners[0], "revision": 4, "previous_report_id": "unrelated"}
    del forged["report_id"]
    forged["report_id"] = digest(forged)
    with manager.engine.begin() as connection:
        connection.execute(
            reports.insert().values(
                report_id=forged["report_id"],
                execution_id=identifier,
                revision=4,
                document=forged,
            )
        )
    with pytest.raises(ValueError, match="ancestry"):
        view.reliability_reports(identifier, limit=1)


def test_cross_sandbox_callback_cannot_taint_the_source(lab, manager):
    source = queue(lab)
    lab.dispatch(source)
    event = deliver(lab, source, 1, "delivered")
    run = "rel_" + uuid.uuid4().hex[:18]
    box = manager.provision(run, load_baseline(), baseline_access())
    with box.transaction() as (_, registry):
        marker = registry["marker"]
    try:
        foreign = NotificationLab(box)
        foreign.register(ACTOR)
        target = queue(foreign)
        foreign.dispatch(target)
        with pytest.raises(ValueError, match="contradictory_callback_identity"):
            foreign.callback(target, event, 1, "delivered")
        assert foreign.evidence(target)["delivery"] == "contradictory"
        assert lab.evidence(source)["delivery"] == "delivered"
        assert not lab.evidence(source)["callback_conflicts"]
        with pytest.raises(ValueError, match="sandbox incarnation"):
            foreign.evidence(source)
    finally:
        manager.cleanup(run, expected_marker=marker)


@pytest.mark.anyio
async def test_publication_recomputes_metrics_and_rejects_rehashed_storage(manager, tmp_path):
    import copy

    from agent_reliability_lab.opsdesk.fixtures import digest
    from agent_reliability_lab.reliability.attestation import authenticate, load_signer
    from agent_reliability_lab.reliability.demo import prepare_reliability_demo
    from agent_reliability_lab.reliability.notifications import (
        publication_attestations,
        report_evidence,
        reports,
    )
    from agent_reliability_lab.reliability.revisions import freeze, report_rows, validated_reports
    from agent_reliability_lab.research.views import ResearchView

    result = await prepare_reliability_demo(manager.engine, tmp_path)
    end = ResearchView(manager.engine).reliability_reports(result["execution_id"])[-1]
    for corruption in (
        "100/1",
        "negative",
        "denominator",
        "value",
        "missing",
        "duplicate",
        "name",
        "version",
        "plausible",
        "nan",
        "extra",
    ):
        next_report = copy.deepcopy(end)
        next_report["previous_report_id"] = end["report_id"]
        rows = next_report["metrics"]
        row = next(r for r in rows if r["name"] == "duplicate_effect")
        if corruption == "100/1":
            row.update(numerator=100, denominator=1, value=100)
        elif corruption == "negative":
            row["numerator"] = -1
        elif corruption == "denominator":
            row["denominator"] = -1
        elif corruption == "value":
            row["value"] = 0.5
        elif corruption == "missing":
            rows.remove(row)
        elif corruption == "duplicate":
            rows.append(row)
        elif corruption == "name":
            row["name"] = "invented"
        elif corruption == "version":
            row["version"] = "reliability-9.0.0"
        elif corruption == "plausible":
            row.update(numerator=1, value=1.0)
        elif corruption == "nan":
            row["value"] = float("nan")
        else:
            row["custom"] = "unsupported"
        with pytest.raises(ValueError, match="reliability metrics"):
            freeze(manager.engine, next_report, 3)

    forged = {**next_report, "revision": 3}
    del forged["report_id"]
    forged["report_id"] = digest(forged)
    with manager.engine.connect() as connection, connection.begin() as transaction:
        snapshot = connection.scalar(
            sa.select(report_evidence.c.snapshot).filter_by(report_id=end["report_id"])
        )
        connection.execute(
            reports.insert().values(
                report_id=forged["report_id"],
                execution_id=result["execution_id"],
                revision=3,
                document=forged,
            )
        )
        connection.execute(
            report_evidence.insert().values(report_id=forged["report_id"], snapshot=snapshot)
        )
        connection.execute(
            publication_attestations.insert().values(
                report_id=forged["report_id"],
                attestation=authenticate(forged, snapshot, load_signer()),
            )
        )
        with pytest.raises(ValueError, match="reliability metrics"):
            list(
                validated_reports(
                    report_rows(connection, result["execution_id"]),
                    result["execution_id"],
                    connection,
                )
            )
        transaction.rollback()

    valid = freeze(manager.engine, {**end, "previous_report_id": end["report_id"]}, 3)
    assert valid["metrics"] == end["metrics"]


@pytest.mark.anyio
async def test_publication_locks_live_outbox_and_historical_bytes_survive(manager, tmp_path):
    from agent_reliability_lab.reliability.demo import prepare_reliability_demo
    from agent_reliability_lab.reliability.metrics import render
    from agent_reliability_lab.reliability.revisions import freeze
    from agent_reliability_lab.research.views import ResearchView

    result = await prepare_reliability_demo(manager.engine, tmp_path)
    view = ResearchView(manager.engine)
    first, end = view.reliability_reports(result["execution_id"])
    request = {**end, "previous_report_id": end["report_id"]}
    with manager.engine.begin() as writer:
        writer.execute(
            outbox.update()
            .where(outbox.c.notification_id == end["provider"]["notification_id"])
            .values(payload_hash="0" * 64)
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(freeze, manager.engine, request, 3)
            with pytest.raises(sa.exc.OperationalError) as failure:
                future.result(timeout=10)
            assert failure.value.orig.sqlstate == "55P03"
    with pytest.raises(ValueError, match="intent or outbox"):
        freeze(manager.engine, request, 3)
    assert view.reliability_reports(result["execution_id"]) == [first, end]
    assert (
        render(first, "json").encode()
        == (tmp_path / first["report_id"] / "reliability.json").read_bytes()
    )


@pytest.mark.anyio
async def test_legacy_label_cannot_verify_unbound_reports(manager, tmp_path):
    from agent_reliability_lab.opsdesk.fixtures import digest
    from agent_reliability_lab.reliability.demo import prepare_reliability_demo
    from agent_reliability_lab.reliability.metrics import render
    from agent_reliability_lab.reliability.notifications import reports
    from agent_reliability_lab.reliability.revisions import freeze, validated_reports
    from agent_reliability_lab.research.views import ResearchView

    run = await prepare_reliability_demo(manager.engine, tmp_path)
    first = ResearchView(manager.engine).reliability_reports(run["execution_id"])[0]
    legacy = {k: v for k, v in first.items() if k != "report_id"}
    legacy["version"] = "reliability-1.0.0"
    legacy["report_id"] = digest(legacy)

    def row(doc):
        return {k: doc[k] for k in ("report_id", "execution_id", "revision")} | {"document": doc}

    with manager.engine.connect() as connection:
        offline = list(validated_reports([row(legacy)], run["execution_id"], connection))[0]
        assert offline.verification == "legacy_unverified"
        for ext in ("json", "csv", "md"):
            assert render(offline, ext) == render(legacy, ext)
    with pytest.raises(ValueError, match="legacy reliability reports cannot be published"):
        freeze(manager.engine, legacy, 1)
    for execution, notification, predecessor in (
        (uuid.uuid4().hex, first["provider"]["notification_id"], None),
        (run["execution_id"], "nonexistent", None),
        (run["execution_id"], first["provider"]["notification_id"], "f" * 64),
    ):
        forged = {
            **legacy,
            "execution_id": execution,
            "previous_report_id": predecessor,
            "provider": {**legacy["provider"], "notification_id": notification},
        }
        del forged["report_id"]
        forged["report_id"] = digest(forged)
        with manager.engine.connect() as connection:
            with pytest.raises(ValueError):
                list(validated_reports([row(forged)], execution, connection))
        if execution != run["execution_id"]:
            with manager.engine.begin() as connection:
                connection.execute(reports.insert().values(**row(forged)))
            with pytest.raises(ValueError, match="missing reliability execution"):
                ResearchView(manager.engine).reliability_reports(execution)


@pytest.mark.anyio
async def test_inspector_uses_sealed_attempt_receipt_and_audit(lab):
    from copy import deepcopy

    from agent_reliability_lab.agent import tables as agent
    from agent_reliability_lab.agent.config import AgentConfig, ModelConfig
    from agent_reliability_lab.agent.demo import call
    from agent_reliability_lab.agent.execution import AgentExecution
    from agent_reliability_lab.mcp.context import operation_identity, receipt_key
    from agent_reliability_lab.opsdesk import tables as business
    from agent_reliability_lab.reliability.inspection import retry_chain

    config = AgentConfig(
        sandbox_run_id=lab.sandbox.run_id,
        **ACTOR.model_dump(),
        domains=["tasks"],
        transport="memory",
        model=ModelConfig(
            script=[
                call("create_task", customer_id="customer_001", title="Audit task"),
                {"answer": "Task created."},
            ]
        ),
    )
    run = AgentExecution(lab.sandbox.engine)
    eid = await run.create("Create a task.", config)
    assert (await run.run(eid, config)).status == "completed"
    with lab.sandbox.transaction() as (connection, _):
        operation = dict(
            connection.execute(sa.select(agent.operations).filter_by(execution_id=eid))
            .mappings()
            .one()
        )
        attempts = [
            dict(r)
            for r in connection.execute(
                sa.select(agent.attempts).filter_by(proposal_id=operation["proposal_id"])
            ).mappings()
        ]
        receipts = [dict(r) for r in connection.execute(sa.select(business.receipts)).mappings()]
        audits = [dict(r) for r in connection.execute(sa.select(business.audit)).mappings()]
    key = receipt_key(
        operation_identity(run.launch(config), "create_task", operation["operation_id"])
    )
    evidence = {
        "execution": {"config": config.model_dump()},
        "operations": [operation],
        "attempts": attempts,
        "provenance": run.store.provenance(eid),
        "receipts": receipts,
        "audits": audits,
    }
    reconciliation = {
        "complete": True,
        "committed": {
            operation["operation_id"]: {
                "receipt_key": key,
                "proposal_id": operation["proposal_id"],
                "audit_sequence": audits[0]["sequence"],
            }
        },
    }
    got = retry_chain(evidence, operation["proposal_id"], reconciliation)
    assert (got["outcome"], got["mutation_evidence"]) == ("committed", "observed")
    from agent_reliability_lab.evaluation.evidence import response_projection

    projected = {**operation, "response": response_projection(operation["response"])}
    frozen = retry_chain(
        {**evidence, "operations": [projected]}, operation["proposal_id"], reconciliation
    )
    assert frozen["outcome"] == "committed"
    mismatched_audit = {**audits[0], "tenant_id": "other"}
    conflict = retry_chain(
        {**evidence, "audits": [mismatched_audit]}, operation["proposal_id"], reconciliation
    )
    assert (conflict["outcome"], conflict["mutation_evidence"]) == ("unknown", "unresolved")
    failed = {**evidence, "operations": [{**operation, "status": "failed"}]}
    status_conflict = retry_chain(failed, operation["proposal_id"], reconciliation)
    assert (
        status_conflict["outcome"],
        status_conflict["logical_status"],
        status_conflict["mutation_evidence"],
    ) == ("contradictory", "failed", "observed")
    for field in ("receipts", "audits", "provenance"):
        broken = {**evidence, field: []}
        assert retry_chain(broken, operation["proposal_id"], reconciliation)["outcome"] == "unknown"
    broken = deepcopy(evidence)
    broken["attempts"][0]["effect"] = "unknown"
    assert (
        retry_chain(broken, operation["proposal_id"], reconciliation)["outcome"] == "contradictory"
    )

    wrong_task = {**evidence, "audits": [{**audits[0], "task_id": "task_001"}]}
    wrong = retry_chain(wrong_task, operation["proposal_id"], reconciliation)
    assert wrong["outcome"] == "unknown"
    assert wrong["mutation_evidence"] == "unresolved"
    wrong_receipt = deepcopy(evidence)
    wrong_receipt["receipts"][0]["response"]["task_id"] = "task_001"
    assert (
        retry_chain(wrong_receipt, operation["proposal_id"], reconciliation)["outcome"] == "unknown"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [TimeoutError, ConnectionError])
async def test_receipt_reuse_follows_attempt_that_reached_mcp(
    manager, tmp_path, monkeypatch, failure
):
    from agent_reliability_lab.agent.config import AgentConfig, Budgets
    from agent_reliability_lab.agent.tool_adapter import ToolSession
    from agent_reliability_lab.reliability import demo
    from agent_reliability_lab.research.views import ResearchView

    monkeypatch.setattr(
        demo, "AgentConfig", lambda **kw: AgentConfig(**kw, budgets=Budgets(max_retries=2))
    )
    call = ToolSession.call
    reached = []

    async def pre_mcp_failure(session, *args, **kwargs):
        ordinal = len(reached) + 1
        reached.append(ordinal != 2)
        if ordinal == 2:
            raise failure("pre-MCP failure")
        return await call(session, *args, **kwargs)

    monkeypatch.setattr(ToolSession, "call", pre_mcp_failure)
    result = await demo.prepare_reliability_demo(manager.engine, tmp_path)
    first, second = ResearchView(manager.engine).reliability_reports(result["execution_id"])
    assert reached == [True, False, True]
    for report in (first, second):
        assert [
            report[k]
            for k in (
                "logical_operation_count",
                "physical_tool_attempts",
                "receipt_count",
                "local_mutations",
            )
        ] == [1, 3, 1, 1]
        chain = report["retry"]
        assert [row["status"] for row in chain["attempts"]] == ["failed", "failed", "succeeded"]
        expected = chain["attempts"][2]["attempt_id"]
        assert [(x["attempt_id"], x["ordinal"]) for x in chain["receipt_reuse_attempts"]] == [
            (expected, 3)
        ]
        assert chain["receipt_reuse"] == "verified for attempt 3"
        first_fault, second_fault = chain["fault_observations"]
        assert first_fault["verified_recovery_attempt_id"] == expected
        assert first_fault["attempt_id"] == chain["attempts"][0]["attempt_id"]
        assert second_fault["attempt_id"] == chain["attempts"][1]["attempt_id"]
        assert second_fault["verified_recovery_attempt_id"] is None
        by_name = {m["name"]: m for m in report["metrics"]}
        assert by_name["retry_deduplication"]["value"] == 1
        assert by_name["verified_recovery"]["unresolved"] == 1


@pytest.mark.anyio
async def test_signed_current_sources_compare_attempts_and_journal(lab, tmp_path, monkeypatch):
    from agent_reliability_lab.agent import tables as agent
    from agent_reliability_lab.agent.persistence import ExecutionStore
    from agent_reliability_lab.reliability import revisions
    from agent_reliability_lab.reliability.demo import run_reliability_demo
    from agent_reliability_lab.reliability.metrics import render
    from agent_reliability_lab.research.views import ResearchView

    engine = lab.sandbox.engine
    summary = await run_reliability_demo(engine, lab.sandbox, tmp_path, transport="memory")
    eid = summary["execution_id"]
    view = ResearchView(engine)
    first, second = view.reliability_reports(eid)
    assert [item.current_state for item in (first, second)] == ["historical", "current"]
    key = second["retry"]["attempts"][1]["attempt_id"]
    attempt = agent.attempts.update().filter_by(attempt_id=key)
    changes = [
        attempt.values(status="failed", error_code="permission_denied"),
        attempt.values(error_code="permission_denied"),
        attempt.values(effect="denied"),
        attempt.values(attempt_id=uuid.uuid4().hex),
        agent.attempts.delete().filter_by(attempt_id=key),
        agent.events.delete().filter_by(execution_id=eid, event_type="tool_call_succeeded"),
    ]
    for change in changes:
        with engine.connect() as connection, connection.begin() as tx:
            if change.table is agent.events:
                connection.exec_driver_sql(
                    "ALTER TABLE opsdesk_agent.events DISABLE TRIGGER immutable_history"
                )
            connection.execute(change)
            check = revisions.current_state(connection, second)
            assert check.status == "inconsistent"
            assert check.reference in (key, eid)
            tx.rollback()

    from streamlit.testing.v1 import AppTest

    with engine.begin() as connection:
        connection.execute(changes[0])
    monkeypatch.setenv(
        "OPSDESK_DASHBOARD_DATABASE_URL", engine.url.render_as_string(hide_password=False)
    )
    ui = AppTest.from_string(
        f"""
import os
from agent_reliability_lab.dashboard.reliability import demo_workspace
from agent_reliability_lab.research.views import ResearchView, readonly_engine
view = ResearchView(readonly_engine(os.environ["OPSDESK_DASHBOARD_DATABASE_URL"]))
demo_workspace(view, {eid!r}, "Reports & Evaluators")
"""
    ).run()
    assert not ui.exception
    assert any("inconsistent" in row.value for row in ui.warning)
    assert any("Physical attempt changed" in row.value for row in ui.caption)
    assert all("Current sources match" not in row.value for row in ui.caption)
    assert view.reliability_reports(eid) == [first, second]
    with engine.begin() as connection:
        connection.execute(attempt.values(status="succeeded", error_code=None))

    def unavailable(*args):
        raise sa.exc.OperationalError("test", {}, RuntimeError("query unavailable"))

    with monkeypatch.context() as checked:
        checked.setattr(revisions, "attempt_inventory", unavailable)
        history = view.reliability_reports(eid)
        assert history == [first, second]
        assert all(d.current_state == "unavailable" for d in history)
    with engine.connect() as connection:
        _, ops, _ = revisions.execution_evidence(connection, eid)
        operation = ops[second["execution_evidence"]["logical_operation_id"]]
    appended = ExecutionStore(engine).begin_attempt(eid, dict(operation), 1, 3, 10)
    assert appended and appended[1] == 3
    recent = view.reliability_reports(eid)[-1]
    assert recent.current_state == "historical"
    assert recent.current_source_reason == "Additional execution evidence is now available."
    assert render(recent, "json") == render(second, "json")


@pytest.mark.anyio
async def test_publication_authentication_rejects_copied_and_modified_revisions(
    lab, tmp_path, monkeypatch
):
    from copy import deepcopy

    from agent_reliability_lab.opsdesk.fixtures import digest
    from agent_reliability_lab.reliability import notifications as tables
    from agent_reliability_lab.reliability.attestation import PRIVATE_FILE, TRUST_DIR
    from agent_reliability_lab.reliability.demo import run_reliability_demo
    from agent_reliability_lab.reliability.revisions import freeze, report_rows, validated_reports
    from agent_reliability_lab.research.views import ResearchView

    engine = lab.sandbox.engine
    run = await run_reliability_demo(engine, lab.sandbox, tmp_path, transport="memory")
    eid = run["execution_id"]
    view = ResearchView(engine)
    first, second = view.reliability_reports(eid)
    identifier = second["provider"]["notification_id"]
    deliver(lab, identifier, 2, "failed")
    assert lab.evidence(identifier)["delivery"] == "contradictory"
    with pytest.raises(ValueError, match="invalid frozen provider observations"):
        freeze(engine, {**second, "previous_report_id": second["report_id"]}, 3)

    with engine.connect() as connection:
        snapshot = connection.scalar(
            sa.select(tables.report_evidence.c.snapshot).filter_by(report_id=second["report_id"])
        )
        original = connection.scalar(
            sa.select(tables.publication_attestations.c.attestation).filter_by(
                report_id=second["report_id"]
            )
        )

    for variant, reason in (
        ("missing", "missing or malformed publication attestation"),
        ("copied", "attestation does not match frozen report"),
        ("altered revision", "ancestry"),
        ("altered predecessor", "ancestry"),
        ("metrics", "attestation does not match frozen report"),
        ("algorithm", "unsupported publication attestation"),
        ("key", "unknown or invalid publication verification key"),
        ("signature", "invalid publication signature"),
        ("snapshot", "attestation does not match frozen report"),
    ):
        forged = deepcopy({**second, "revision": 3, "previous_report_id": second["report_id"]})
        proposed_snapshot = deepcopy(snapshot)
        attestation = deepcopy(original)
        if variant == "altered revision":
            forged["revision"] = 4
        if variant == "altered predecessor":
            forged["previous_report_id"] = first["report_id"]
        if variant == "metrics":
            forged["metrics"][0].update(numerator=100, value=100)
        if variant == "algorithm":
            attestation["manifest"]["algorithm"] = "none"
        if variant == "key":
            attestation["manifest"]["key_id"] = "a" * 64
        if variant == "signature":
            attestation["signature"] = "00" * 64
        if variant == "snapshot":
            proposed_snapshot["local"]["mutation_count"] = 0
        forged["pinned_evidence_hash"] = digest(proposed_snapshot)
        del forged["report_id"]
        forged["report_id"] = digest(forged)
        with engine.connect() as connection, connection.begin() as transaction:
            connection.execute(
                tables.reports.insert().values(
                    execution_id=eid, report_id=forged["report_id"], revision=3, document=forged
                )
            )
            connection.execute(
                tables.report_evidence.insert().values(
                    report_id=forged["report_id"], snapshot=proposed_snapshot
                )
            )
            if variant != "missing":
                connection.execute(
                    tables.publication_attestations.insert().values(
                        report_id=forged["report_id"], attestation=attestation
                    )
                )
            verified_prefix = validated_reports(report_rows(connection, eid), eid, connection)
            assert next(verified_prefix) == first
            assert next(verified_prefix) == second
            with pytest.raises(ValueError, match=reason):
                next(verified_prefix)
            transaction.rollback()

    live = lab.evidence(identifier)
    from agent_reliability_lab.reliability.diagnostics import provider_gaps

    live["unknown_reasons"] = provider_gaps(live)
    candidate = {
        **second,
        "provider": live,
        "provider_evidence_hash": digest(live),
        "previous_report_id": second["report_id"],
    }
    candidate.pop("metrics")
    with monkeypatch.context() as isolated:
        isolated.delenv(PRIVATE_FILE)
        with pytest.raises(ValueError, match="signing key is not configured"):
            freeze(engine, candidate, 3)
        assert view.reliability_reports(eid) == [first, second]
    third = freeze(engine, candidate, 3)
    assert third["provider"]["delivery"] == "contradictory"
    assert third["report_id"] != second["report_id"]
    with monkeypatch.context() as isolated:
        isolated.delenv(TRUST_DIR)
        with pytest.raises(ValueError, match="trust directory"):
            view.reliability_reports(eid)


@pytest.mark.anyio
async def test_signed_history_survives_provider_and_logical_status_changes(manager, tmp_path):
    import os
    import subprocess
    import sys

    from agent_reliability_lab.agent import tables as agent
    from agent_reliability_lab.reliability.attestation import PRIVATE_FILE
    from agent_reliability_lab.reliability.demo import prepare_reliability_demo
    from agent_reliability_lab.reliability.metrics import render
    from agent_reliability_lab.reliability.revisions import freeze
    from agent_reliability_lab.research.views import ResearchView

    engine = manager.engine
    data = await prepare_reliability_demo(engine, tmp_path, transport="stdio")
    eid = data["execution_id"]
    view = ResearchView(engine)
    first, second = view.reliability_reports(eid)
    assert [first.current_state, second.current_state] == ["historical", "current"]
    candidate = {**second, "previous_report_id": second["report_id"]}
    logical = second["execution_evidence"]["logical_operation_id"]
    update = agent.operations.update().filter_by(operation_id=logical)
    with engine.begin() as connection:
        connection.execute(update.values(status="failed"))
    with pytest.raises(ValueError, match="contradictory logical operation lifecycle"):
        freeze(engine, candidate, 3)
    with engine.begin() as connection:
        connection.execute(update.values(status="succeeded"))
        connection.execute(
            provider.update()
            .filter_by(notification_id=second["provider"]["notification_id"])
            .values(payload_hash="f" * 64)
        )
    with pytest.raises(ValueError, match="contradictory frozen provider binding"):
        freeze(engine, candidate, 3)
    archived = view.reliability_reports(eid)
    assert [doc.current_state for doc in archived] == ["inconsistent", "inconsistent"]
    assert archived == [first, second]
    for doc in archived:
        for ext in ("json", "csv", "md"):
            assert (
                render(doc, ext).encode()
                == (tmp_path / doc["report_id"] / f"reliability.{ext}").read_bytes()
            )
    script = """
import sys
from agent_reliability_lab.opsdesk.database import engine_from_env
from agent_reliability_lab.research.views import ResearchView
docs = ResearchView(engine_from_env()).reliability_reports(sys.argv[1])
assert [item['report_id'] for item in docs] == sys.argv[2:4]
assert all(item.verification == 'verified' for item in docs)
"""
    child_env = {k: v for k, v in os.environ.items() if k != PRIVATE_FILE}
    child = subprocess.run(
        [sys.executable, "-B", "-c", script, eid, first["report_id"], second["report_id"]],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert child.returncode == 0, child.stderr


@pytest.mark.anyio
async def test_event_writer_cannot_cross_signed_publication_boundary(lab, tmp_path, monkeypatch):
    from threading import Event

    from agent_reliability_lab.reliability import revisions
    from agent_reliability_lab.reliability.demo import run_reliability_demo
    from agent_reliability_lab.research.views import ResearchView

    engine = lab.sandbox.engine
    run = await run_reliability_demo(engine, lab.sandbox, tmp_path, transport="memory")
    view = ResearchView(engine)
    latest = view.reliability_reports(run["execution_id"])[-1]
    nid = latest["provider"]["notification_id"]
    captured, resume = Event(), Event()
    capture = revisions._capture

    def paused_capture(*args):
        snap = capture(*args)
        captured.set()
        assert resume.wait(10)
        return snap

    monkeypatch.setattr(revisions, "_capture", paused_capture)
    candidate = {**latest, "previous_report_id": latest["report_id"]}
    with ThreadPoolExecutor(2) as pool:
        publication = pool.submit(revisions.freeze, engine, candidate, 3)
        try:
            assert captured.wait(5)
            started = Event()

            def callback():
                started.set()
                return deliver(lab, nid, 2, "failed")

            writer = pool.submit(callback)
            assert started.wait(5)
            # The authoritative write begins with the notification lock.
            assert not writer.done()
        finally:
            resume.set()
        assert publication.result(timeout=10)["provider"]["delivery"] == "delivered"
        assert writer.result(timeout=10)
    _, _, frozen = view.reliability_reports(run["execution_id"])
    assert frozen.current_state == "inconsistent"
    assert lab.evidence(nid)["delivery"] == "contradictory"
