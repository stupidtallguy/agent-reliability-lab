"""Consistent sandbox snapshots and a bounded projection of the durable agent ledger."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from agent_reliability_lab.agent import tables as a
from agent_reliability_lab.agent.persistence import ExecutionStore
from agent_reliability_lab.agent.state import TERMINAL
from agent_reliability_lab.evaluation.contracts import Evidence
from agent_reliability_lab.opsdesk import tables as b
from agent_reliability_lab.opsdesk.database import Sandbox
from agent_reliability_lab.opsdesk.fixtures import benchmark_state, digest, logical_state


def portable(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): portable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [portable(item) for item in value]
    return value


def capture_initial(sandbox: Sandbox) -> dict:
    with sandbox.transaction(exclusive=True) as (connection, registry):
        full = logical_state(connection)
        if (
            digest(full) != registry["initial_hash"]
            or digest(registry["seed_spec"]) != registry["seed_hash"]
        ):
            raise ValueError("initial fixture integrity check failed")
        return dict(
            initial=benchmark_state(connection),
            initial_full=full,
            marker=registry["marker"],
            seed_hash=registry["seed_hash"],
            initial_hash=registry["initial_hash"],
            fixture_hash=digest(registry["seed_spec"]["environment"]),
            tool_access=registry["tool_access"],
        )


EVENT_KEYS = {
    "schema_version",
    "correlation_id",
    "tool_call_id",
    "logical_operation_id",
    "attempt_id",
    "request_id",
    "ordinal",
    "tool",
    "error_code",
    "effect",
    "status",
    "reason",
    "call_count",
    "arguments_hash",
    "actor_reference",
    "sandbox_run_id",
    "provider",
    "model",
    "reported_model",
    "input_hash",
    "injection_id",
    "configuration_hash",
    "matched",
    "dispatch_ordinal",
    "boundary",
    "underlying_executed",
    "underlying_success",
    "original_response_hash",
    "transformed_response_hash",
    "observed_response_hash",
    "payload_delivered",
    "response_hash",
}
DATA_KEYS = {
    "task_id",
    "order_id",
    "customer_id",
    "document_id",
    "version",
    "status",
    "next_after_id",
    "trust_classification",
}


def data_projection(value):
    if not isinstance(value, dict):
        return value
    result = {key: item for key, item in value.items() if key in DATA_KEYS}
    if "items" in value:
        result["items"] = [data_projection(item) for item in value["items"]]
    return result


def response_projection(response: dict | None) -> dict | None:
    if response is None:
        return None
    return {
        "error": response.get("error"),
        "data": data_projection(response.get("data")),
        "provenance": response.get("provenance"),
        "source": response.get("source"),
        "response_hash": digest(response),
    }


def config_projection(config: dict) -> dict:
    """The full host config hash is retained separately from this evidence projection."""
    return {
        **{key: value for key, value in config.items() if key != "model"},
        "model": {key: value for key, value in config["model"].items() if key != "script"},
    }


def collect(
    engine: Engine,
    sandbox: Sandbox,
    execution_id: str,
    initial: dict,
    catalog: list[dict],
    observed_seconds: float | None,
) -> Evidence:
    # Claim before the exclusive snapshot: no concurrent resume can race collection.
    store = ExecutionStore(engine)
    with store.claim(execution_id), sandbox.transaction(exclusive=True) as (connection, registry):

        def rows(table, condition=None, ordering=()):
            query = sa.select(table)
            if condition is not None:
                query = query.where(condition)
            return portable(
                [dict(row) for row in connection.execute(query.order_by(*ordering)).mappings()]
            )

        execution = rows(a.executions, a.executions.c.execution_id == execution_id)[0]
        if registry["marker"] != initial["marker"] or execution["context"] != {
            "marker": registry["marker"],
            "seed_hash": registry["seed_hash"],
        }:
            raise ValueError("execution sandbox incarnation mismatch")
        if execution["config"]["sandbox_run_id"] != sandbox.run_id:
            raise ValueError("execution run association mismatch")
        operations = rows(
            a.operations,
            a.operations.c.execution_id == execution_id,
            (a.operations.c.turn, a.operations.c.position),
        )
        identifiers = [row["proposal_id"] for row in operations]
        attempts = rows(
            a.attempts,
            a.attempts.c.proposal_id.in_(identifiers),
            (a.attempts.c.started_at, a.attempts.c.attempt_id),
        )
        events = rows(a.events, a.events.c.execution_id == execution_id, (a.events.c.sequence,))
        requests = rows(
            a.requests,
            a.requests.c.execution_id == execution_id,
            (a.requests.c.turn, a.requests.c.request_id),
        )
        hashes = {
            "events": digest(events),
            "operations": digest(operations),
            "attempts": digest(attempts),
            "requests": digest(requests),
            "catalog": digest(catalog),
        }
        for event in events:
            event["payload"] = {
                key: value for key, value in event["payload"].items() if key in EVENT_KEYS
            }
        for operation in operations:
            operation["response"] = response_projection(operation["response"])
        request_events = {
            event["payload"]["request_id"]: event["timestamp"]
            for event in events
            if event["event_type"] == "model_request"
        }
        for request in requests:
            reply = request.pop("reply")
            if reply is not None:
                request["answer_hash"] = digest(reply.get("answer"))
            request.update(
                usage=reply["usage"] if reply else None,
                model=reply.get("reported_model") if reply else None,
                calls=reply.get("calls", []) if reply else [],
                timestamp=request_events.get(request["request_id"]),
            )
        # Config scripts and conversation text already live in the agent store.
        execution["config"] = config_projection(execution["config"])
        return Evidence(
            execution_id=execution_id,
            sandbox_run_id=sandbox.run_id,
            **initial,
            final=benchmark_state(connection),
            final_full=logical_state(connection),
            execution=execution,
            catalog=[
                {key: tool[key] for key in ("name", "domain", "description", "input_schema")}
                | {"output_schema_hash": digest(tool["output_schema"])}
                for tool in catalog
            ],
            events=events,
            operations=operations,
            attempts=attempts,
            requests=requests,
            source_hashes=hashes,
            provenance=store.provenance(execution_id),
            receipts=rows(b.receipts, ordering=tuple(b.receipts.primary_key.columns)),
            audits=rows(b.audit, ordering=(b.audit.c.sequence,)),
            observed_seconds=observed_seconds,
            timing_complete=execution["timing_complete"] and execution["status"] in TERMINAL,
        )


def normalized_task(record: dict) -> dict:
    """Compare canonical snapshots (+00:00) with Pydantic receipt timestamps (Z)."""
    result = {key: value for key, value in record.items() if key != "tenant_id"}
    for key in ("created_at", "updated_at"):
        if key in result:
            result[key] = (
                datetime.fromisoformat(result[key].replace("Z", "+00:00"))
                .astimezone(UTC)
                .isoformat()
            )
    return json.loads(json.dumps(result, sort_keys=True))
