"""A scripted agent and an isolated synthetic provider with two frozen observations."""

import uuid

import sqlalchemy as sa

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
from agent_reliability_lab.reliability.metrics import export
from agent_reliability_lab.reliability.notifications import (
    TOOL,
    NotificationLab,
    intents,
    outbox,
)
from agent_reliability_lab.reliability.revisions import freeze


async def prepare_reliability_demo(engine, output, *, transport="memory"):
    manager = SandboxManager(engine)
    manager.initialize()
    run = "rel_" + uuid.uuid4().hex[:18]
    sandbox = manager.provision(run, load_baseline(), baseline_access())
    with sandbox.transaction() as (_, registry):
        marker = registry["marker"]
    try:
        return await run_reliability_demo(engine, sandbox, output, transport=transport)
    finally:
        manager.cleanup(run, expected_marker=marker)


async def run_reliability_demo(engine, sandbox, output, *, transport):
    run = sandbox.run_id
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
                with engine.begin() as connection:
                    receipt = connection.scalar(
                        sa.select(intents.c.receipt).filter_by(
                            notification_id=response["data"]["notification_id"],
                        )
                    )
                    if receipt != response["data"]:
                        raise ValueError("first attempt did not commit its receipt")
                    execution.store._seal(
                        connection,
                        execution_id,
                        "reliability_receipt_observed",
                        operation["operation_id"],
                        {
                            "proposal_id": operation["proposal_id"],
                            "receipt_hash": digest(receipt),
                        },
                    )
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
    provenance = execution.store.provenance(execution_id)
    chain = retry_chain(
        {
            "operations": [operation],
            "attempts": attempts,
            "provenance": provenance,
            "notification_intent": local[0],
        },
        operation["proposal_id"],
        {
            "complete": True,
            "committed": {
                operation["operation_id"]: {
                    "notification_id": identifier,
                    "receipt_hash": digest(receipts[0]),
                    "outbox_payload_hash": queued,
                }
            },
        },
    )
    # Publication independently verifies the sealed observation and attempts.
    chain["outcome"] = "committed"
    chain["logical_reconciliation"] = "verified"
    chain["receipt_reuse"] = "verified for attempt 2"

    lab.dispatch(identifier, "lose_ack")
    lab.dispatch(identifier)
    common = dict(
        purpose="scripted_infrastructure_validation",
        categories=["retry_concurrency", "synthetic_external_effect"],
        execution_id=execution_id,
        execution_evidence=dict(
            execution_id=execution_id,
            logical_operation_id=operation["operation_id"],
            ledger_head=provenance[-1]["record_hash"],
            receipt_hash=digest(receipts[0]),
            operation_key=expected_key,
        ),
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
            event_id = lab.issue_event(identifier, 1, "delivered")
            lab.callback(identifier, event_id, 1, "delivered")
        evidence = lab.evidence(identifier)
        evidence["unknown_reasons"] = provider_gaps(evidence)
        document = freeze(
            engine,
            dict(
                **common,
                provider=evidence,
                provider_evidence_hash=digest(evidence),
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
