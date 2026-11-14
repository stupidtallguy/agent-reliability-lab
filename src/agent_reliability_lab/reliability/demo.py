"""A scripted agent and an isolated synthetic provider with two frozen observations."""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from agent_reliability_lab.agent import tables as agent
from agent_reliability_lab.agent.config import AgentConfig, ModelConfig
from agent_reliability_lab.agent.demo import call
from agent_reliability_lab.agent.execution import AgentExecution
from agent_reliability_lab.agent.graph import observation_error
from agent_reliability_lab.mcp.context import operation_identity, receipt_key
from agent_reliability_lab.opsdesk.contracts import ActorContext
from agent_reliability_lab.opsdesk.database import SandboxManager
from agent_reliability_lab.opsdesk.fixtures import baseline_access, digest, load_baseline
from agent_reliability_lab.reliability.diagnostics import provider_gaps
from agent_reliability_lab.reliability.inspection import retry_chain
from agent_reliability_lab.reliability.metrics import VERSION, export, revised_metrics
from agent_reliability_lab.reliability.notifications import (
    TOOL,
    NotificationLab,
    intents,
    outbox,
    reports,
)


def freeze(engine, document, revision):
    document = {**document, "version": VERSION, "revision": revision}
    document["report_id"] = digest(document)
    with engine.begin() as connection:
        written = connection.execute(
            insert(reports)
            .values(
                report_id=document["report_id"],
                execution_id=document["execution_id"],
                revision=revision,
                document=document,
            )
            .on_conflict_do_nothing()
            .returning(reports.c.report_id)
        ).scalar_one_or_none()
        if written is None:
            existing = connection.scalar(
                sa.select(reports.c.document).where(
                    reports.c.report_id == document["report_id"],
                )
            )
            if existing != document:
                raise ValueError("reliability report revision conflict")
    return document


async def prepare_reliability_demo(engine, output, *, transport="memory"):
    manager = SandboxManager(engine)
    manager.initialize()
    run = "rel_" + uuid.uuid4().hex[:18]
    sandbox = manager.provision(run, load_baseline(), baseline_access())
    actor = ActorContext(actor_id="support_001", tenant_id="opsdesk")
    lab = NotificationLab(sandbox)
    lab.register(actor)
    config = AgentConfig(
        sandbox_run_id=run,
        **actor.model_dump(),
        domains=["notifications"],
        transport=transport,
        model=ModelConfig(
            script=[
                call(TOOL, customer_id="customer_001", template="order_status"),
                {"answer": "The synthetic notification was queued. Delivery remains unknown."},
            ]
        ),
    )
    execution = AgentExecution(engine)
    execution_id = await execution.create("Queue a synthetic order update.", config)
    receipts = []

    def lose_first_ack(operation, response):
        if operation["tool"] == TOOL and response.get("error") is None:
            receipts.append(response["data"])
            if len(receipts) == 1:
                return observation_error("transport_unavailable", retryable=True)
        return None

    run_result = await execution.run(execution_id, config, after_dispatch=lose_first_ack)
    if run_result.status != "completed" or len(receipts) != 2 or receipts[0] != receipts[1]:
        raise RuntimeError("The reliability demonstration could not verify the local replay")
    identifier = receipts[0]["notification_id"]
    with sandbox.transaction() as (connection, registry):
        local = (
            connection.execute(
                sa.select(intents).where(
                    intents.c.marker == registry["marker"],
                )
            )
            .mappings()
            .all()
        )
        queued = connection.scalar(
            sa.select(outbox.c.payload_hash).where(
                outbox.c.notification_id == identifier,
            )
        )
        if (
            len(local) != 1
            or local[0]["notification_id"] != identifier
            or local[0]["receipt"] != receipts[0]
            or queued != local[0]["payload_hash"]
        ):
            raise RuntimeError("Notification intent and outbox do not reconcile")
    with engine.connect() as connection:
        operation = dict(
            connection.execute(
                sa.select(agent.operations).where(
                    agent.operations.c.execution_id == execution_id,
                )
            )
            .mappings()
            .one()
        )
        attempts = (
            connection.execute(
                sa.select(agent.attempts).where(
                    agent.attempts.c.proposal_id == operation["proposal_id"],
                )
            )
            .mappings()
            .all()
        )
    expected_key = receipt_key(
        operation_identity(execution.launch(config), TOOL, operation["operation_id"])
    )
    if (
        local[0]["operation_key"] != expected_key
        or local[0]["payload_hash"] != operation["arguments_hash"]
    ):
        raise RuntimeError("Notification receipt does not match the signed logical operation")
    chain = retry_chain(
        {
            "operations": [operation],
            "attempts": attempts,
            "provenance": execution.store.provenance(execution_id),
        },
        operation["proposal_id"],
        {
            "committed": {
                operation["operation_id"]: {
                    "notification_id": identifier,
                    "receipt_hash": digest(receipts[0]),
                    "outbox_payload_hash": queued,
                }
            }
        },
    )
    chain["attempts"][0]["receipt_reused"] = None
    chain["attempts"][1]["receipt_reused"] = True
    chain["receipt_reuse"] = "verified for attempt 2 in the controlled demonstration"
    lab.dispatch(identifier, "lose_ack")
    lab.dispatch(identifier)
    common = dict(
        purpose="scripted_infrastructure_validation",
        categories=["retry_concurrency", "synthetic_external_effect"],
        execution_id=execution_id,
        sandbox_run_id=run,
        retry=chain,
        local_mutations=len(local),
        logical_operation_count=1,
        physical_tool_attempts=len(attempts),
        receipt_count=len(local),
        live_model_requests=0,
        evidence_source="sealed_journal_and_local_provider",
    )
    revisions = []
    for revision in (1, 2):
        if revision == 2:
            lab.callback(identifier, "delayed_confirmation", 1, "delivered")
        evidence = lab.evidence(identifier)
        evidence["unknown_reasons"] = provider_gaps(evidence)
        document = freeze(
            engine,
            dict(
                **common,
                provider=evidence,
                metrics=revised_metrics(evidence, chain["attempts"], receipt_verified=True),
                previous_report_id=revisions[-1]["report_id"] if revisions else None,
            ),
            revision,
        )
        folder = export(document, output)
        revisions.append(
            {
                "report_id": document["report_id"],
                "delivery": evidence["delivery"],
                "revision": revision,
                "exports": str(folder),
            }
        )
    return dict(**common, revisions=revisions, scope="reliability_" + execution_id)
