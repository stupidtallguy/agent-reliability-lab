"""Serial append and independent read validation for reliability report revisions."""

import sqlalchemy as sa

from agent_reliability_lab.agent import tables as agent
from agent_reliability_lab.agent.provenance import portable, verify
from agent_reliability_lab.mcp.context import receipt_key
from agent_reliability_lab.opsdesk import tables as business
from agent_reliability_lab.opsdesk.database import lock
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.reliability import notifications as n
from agent_reliability_lab.reliability.attestation import (
    authenticate,
    load_signer,
    verify_attestation,
)
from agent_reliability_lab.reliability.metrics import UNSIGNED_VERSIONS, VERSION
from agent_reliability_lab.reliability.notifications import (
    acknowledgments,
    callback_conflicts,
    delivery,
    dispatches,
    intent_conflicts,
    issued_events,
    provider_bindings,
    reports,
)
from agent_reliability_lab.reliability.notifications import (
    provider as provider_records,
)
from agent_reliability_lab.reliability.publication import (
    canonical_metrics,
    require_metrics,
    select_chain,
)

_FIXED = (
    "sandbox_run_id",
    "retry",
    "local_mutations",
    "logical_operation_count",
    "physical_tool_attempts",
    "receipt_count",
    "evidence_source",
    "execution_evidence",
)


def report_rows(connection, execution_id):
    return connection.execute(
        sa.select(reports)
        .where(reports.c.execution_id == execution_id)
        .order_by(reports.c.revision)
    ).mappings()


def execution_evidence(connection, execution_id):
    execution = (
        connection.execute(
            sa.select(agent.executions).filter_by(
                execution_id=execution_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if not execution:
        raise ValueError("missing reliability execution")
    operations = {
        row["operation_id"]: row
        for row in connection.execute(
            sa.select(agent.operations).filter_by(execution_id=execution_id)
        ).mappings()
    }
    records = list(
        connection.scalars(
            sa.select(agent.provenance.c.record)
            .filter_by(
                execution_id=execution_id,
            )
            .order_by(agent.provenance.c.sequence)
        )
    )
    verify(records, execution_id)
    if digest(execution["config"]) != execution["config_hash"] or (
        records[0]["body"].get("config_hash") != execution["config_hash"]
        or records[0]["body"].get("context") != execution["context"]
    ):
        raise ValueError("contradictory reliability execution binding")
    return execution, operations, records


class ReportDocument(dict):
    """Verification is presentation metadata and never changes serialized report bytes."""

    @property
    def verification(self):
        return "verified" if self["version"] == VERSION else "legacy_unverified"

    current_state = None


def _historical_reference(connection, document):
    execution_id = document["execution_id"]
    identifier = document["provider"]["notification_id"]
    execution, operations, _ = execution_evidence(connection, execution_id)
    intent = n.lookup(connection, n.intents, identifier)
    if (
        not intent
        or intent["run_id"] != execution["config"]["sandbox_run_id"]
        or intent["marker"] != execution["context"]["marker"]
        or intent["actor_id"] != execution["config"]["actor_id"]
        or intent["tenant_id"] != execution["config"]["tenant_id"]
        or not any(
            row["tool"] == n.TOOL and (row.get("response") or {}).get("data") == intent["receipt"]
            for row in operations.values()
        )
    ):
        raise ValueError("unverifiable legacy report ownership")


def _lock_sources(connection, identifier):
    lock(connection, "notification:" + identifier)
    # SHARE conflicts with INSERT/UPDATE/DELETE even for direct SQL. This short,
    # synthetic-only publication transaction takes the same advisory lock as
    # dispatch/callback before acquiring table locks. Queueing uses no such lock.
    # NOWAIT avoids deadlocks with writers holding staged table locks.
    sources = (
        n.admissions,
        n.intents,
        n.outbox,
        n.provider,
        n.provider_bindings,
        n.delivery,
        n.issued_events,
        n.callback_conflicts,
        n.dispatches,
        n.intent_conflicts,
        n.acknowledgments,
        business.registry,
        agent.executions,
        agent.operations,
        agent.attempts,
        agent.provenance,
    )
    connection.exec_driver_sql(
        "LOCK TABLE "
        + ", ".join(sorted(table.fullname for table in sources))
        + " IN SHARE MODE NOWAIT"
    )


def _capture(connection, document, execution, operation):
    identifier = document["provider"]["notification_id"]
    local = select_chain(
        connection,
        execution,
        operation,
        identifier,
        document["execution_evidence"]["operation_key"],
    )
    provider = provider_population(connection, identifier)
    validate_provider_evidence(provider, document["provider"])
    attempts = [
        {
            key: row[key]
            for key in ("proposal_id", "attempt_id", "ordinal", "status", "error_code", "effect")
        }
        for row in connection.execute(
            sa.select(agent.attempts)
            .filter_by(
                proposal_id=operation["proposal_id"],
            )
            .order_by(agent.attempts.c.ordinal)
        ).mappings()
    ]
    return {"local": local, "attempts": attempts, "provider": provider}


_OBSERVATIONS = (
    (delivery, "delivery_events"),
    (callback_conflicts, "callback_conflicts"),
    (dispatches, "provider_attempts"),
    (intent_conflicts, "rejected_conflicting_intents"),
)


def provider_population(connection, identifier):
    def rows(table):
        return sorted(
            (
                dict(row)
                for row in connection.execute(
                    sa.select(table).filter_by(notification_id=identifier)
                ).mappings()
            ),
            key=digest,
        )

    binding = n.lookup(connection, provider_bindings, identifier)
    request = n.lookup(connection, provider_records, identifier)
    return dict(
        binding=dict(binding) if binding else None,
        request=dict(request) if request else None,
        acknowledged=bool(n.lookup(connection, acknowledgments, identifier)),
        issued=rows(issued_events),
        **{key: rows(table) for table, key in _OBSERVATIONS},
    )


def provider_outcome(population):
    statuses = {event["status"] for event in population["delivery_events"]} - {"pending"}
    return (
        "contradictory"
        if population["callback_conflicts"] or len(statuses) > 1
        else "provider_rejected"
        if population["binding"]["status"] == "rejected"
        else next(iter(statuses), "unknown")
    )


def validate_provider_evidence(population, provider):
    identifier = provider["notification_id"]
    binding = population["binding"]
    request = population["request"]
    if (
        not binding
        or not request
        or binding["notification_id"] != identifier
        or request["notification_id"] != identifier
        or request["status"] != binding["status"]
        or request["payload_hash"] != provider.get("payload_hash")
        or binding["provider_operation_id"] != provider.get("provider_operation_id")
        or binding["status"] != provider.get("provider")
    ):
        raise ValueError("missing or contradictory frozen provider binding")
    for _, key in _OBSERVATIONS:
        observed = provider.get(key)
        if not isinstance(observed, list):
            raise ValueError("missing frozen provider observations")
        if sorted(observed, key=digest) != population[key]:
            raise ValueError("invalid frozen provider observations")
    acknowledged = population["acknowledged"]
    if provider.get("acknowledged") is not acknowledged or (
        provider.get("outbox") != ("acknowledged" if acknowledged else "pending")
    ):
        raise ValueError("invalid frozen provider acknowledgment")
    issued = {event["event_id"]: event for event in population["issued"]}
    if any(
        event["notification_id"] != identifier
        or event["provider_operation_id"] != binding["provider_operation_id"]
        or event["payload_hash"] != provider["payload_hash"]
        or event["event_id"]
        != digest([binding["provider_operation_id"], event["sequence"], event["status"]])
        or request["status"] != "accepted"
        for event in issued.values()
    ):
        raise ValueError("invalid issued delivery event authority")
    for event in provider["delivery_events"]:
        authority = issued.get(event["event_id"], {})
        if any(authority.get(key) != value for key, value in event.items()):
            raise ValueError("invalid frozen provider event authority")
    if provider_outcome(population) != provider.get("delivery"):
        raise ValueError("invalid frozen delivery outcome")


def validated_reports(rows, execution_id, connection, *, candidate=None):
    previous = None
    for revision, row in enumerate(rows, 1):
        document = row["document"]
        if (
            not isinstance(document, dict)
            or row["execution_id"] != execution_id
            or document.get("execution_id") != execution_id
            or row["revision"] != revision
            or document.get("revision") != revision
            or row["report_id"] != document.get("report_id")
            or row["report_id"] != digest({k: v for k, v in document.items() if k != "report_id"})
            or document.get("previous_report_id") != (previous and previous["report_id"])
        ):
            raise ValueError("invalid reliability report ancestry or identity")
        provider = document.get("provider")
        if not isinstance(provider, dict) or not provider.get("notification_id"):
            raise ValueError("missing reliability notification evidence")
        if document.get("version") not in {VERSION, *UNSIGNED_VERSIONS}:
            raise ValueError("unsupported reliability report version")
        if document.get("version") != VERSION:
            _historical_reference(connection, document)
        else:
            if candidate is not None and candidate[0] == row["report_id"]:
                _, snapshot, attestation = candidate
            else:
                snapshot = connection.scalar(
                    sa.select(n.report_evidence.c.snapshot).filter_by(report_id=row["report_id"])
                )
                attestation = connection.scalar(
                    sa.select(n.publication_attestations.c.attestation).filter_by(
                        report_id=row["report_id"]
                    )
                )
            if not snapshot or document.get("pinned_evidence_hash") != digest(snapshot):
                raise ValueError("missing or contradictory pinned reliability evidence")
            verify_attestation(document, snapshot, attestation)
            binding = document.get("execution_evidence") or {}
            retry = document.get("retry") or {}
            execution = snapshot["execution"]
            operation = snapshot["operation"]
            records = snapshot["records"]
            config = execution["config"]
            key = receipt_key(
                {
                    "run": config["sandbox_run_id"],
                    "actor": config["actor_id"],
                    "tenant": config["tenant_id"],
                    "tool": retry.get("tool"),
                    "operation": binding.get("logical_operation_id"),
                }
            )
            receipt = retry.get("receipt") or {}
            if (
                binding.get("execution_id") != execution_id
                or operation["execution_id"] != execution_id
                or operation["operation_id"] != binding.get("logical_operation_id")
                or execution["context"] != records[0]["body"].get("context")
                or execution["config_hash"] != records[0]["body"].get("config_hash")
                or binding.get("logical_operation_id") != retry.get("logical_operation_id")
                or (retry.get("receipt") or {}).get("notification_id")
                != provider["notification_id"]
                or not operation
                or operation["proposal_id"] != retry.get("proposal_id")
                or operation["tool"] != n.TOOL
                or operation["tool"] != retry.get("tool")
                or (operation.get("response") or {}).get("data", {}).get("notification_id")
                != provider["notification_id"]
                or binding.get("ledger_head") != records[-1]["record_hash"]
                or binding.get("operation_key") != key
                or binding.get("receipt_hash") != digest(operation["response"]["data"])
                or binding.get("receipt_hash") != receipt.get("receipt_hash")
                or provider.get("payload_hash") != operation["arguments_hash"]
                or document.get("sandbox_run_id") != config["sandbox_run_id"]
                or document.get("provider_evidence_hash") != digest(provider)
            ):
                raise ValueError("invalid reliability execution evidence")
            validate_provider_evidence(snapshot["provider"], provider)
            require_metrics(
                document.get("metrics"), canonical_metrics(document, snapshot, operation, records)
            )
        if previous:
            older = previous["provider"]
            if (
                document.get("version") != previous.get("version")
                or any(document.get(k) != previous.get(k) for k in _FIXED)
                or any(
                    provider.get(k) != older.get(k)
                    for k in ("notification_id", "provider_operation_id", "payload_hash")
                )
                or any(
                    item not in provider.get(key, [])
                    for key in (
                        "delivery_events",
                        "provider_attempts",
                        "callback_conflicts",
                        "rejected_conflicting_intents",
                    )
                    for item in older.get(key, [])
                )
            ):
                raise ValueError("incompatible reliability revision evidence")
        yield ReportDocument(document)
        previous = document


def freeze(engine, document, revision):
    submitted = document
    execution_id = document["execution_id"]
    if document.get("version", VERSION) != VERSION:
        raise ValueError("legacy reliability reports cannot be published")
    document = {k: v for k, v in document.items() if k not in {"report_id", "pinned_evidence_hash"}}
    document.update(version=VERSION, revision=revision)
    with engine.begin() as connection:
        lock(connection, "reliability-report:" + execution_id)
        rows = list(report_rows(connection, execution_id))
        existing = next((row for row in rows if row["revision"] == revision), None)
        if existing is not None:
            if existing["document"] != submitted:
                raise ValueError("reliability report revision conflict")
            list(validated_reports(rows, execution_id, connection))
            return ReportDocument(existing["document"])
        if revision != len(rows) + 1 or document.get("previous_report_id") != (
            rows[-1]["report_id"] if rows else None
        ):
            raise ValueError("invalid reliability report ancestry or identity")
        private = load_signer()
        # Pin the source tables before reading the operation, its ledger and attempts.
        _lock_sources(connection, document["provider"]["notification_id"])
        execution, operations, records = execution_evidence(connection, execution_id)
        operation = operations.get(document["execution_evidence"].get("logical_operation_id"))
        if not operation or operation["tool"] != n.TOOL:
            raise ValueError("missing reliability operation")
        snapshot = _capture(connection, document, execution, operation)
        snapshot.update(
            execution={
                "config": {
                    key: execution["config"][key]
                    for key in ("sandbox_run_id", "actor_id", "tenant_id")
                },
                "config_hash": execution["config_hash"],
                "context": execution["context"],
            },
            operation=portable(dict(operation)),
            records=records,
        )
        canonical = canonical_metrics(document, snapshot, operation, records)
        if "metrics" in submitted:
            require_metrics(submitted["metrics"], canonical)
        document["metrics"] = canonical
        document["pinned_evidence_hash"] = digest(snapshot)
        document["report_id"] = digest(document)
        attestation = authenticate(document, snapshot, private)
        row = {k: document[k] for k in ("report_id", "execution_id", "revision")} | {
            "document": document
        }
        list(
            validated_reports(
                [*rows, row],
                execution_id,
                connection,
                candidate=(row["report_id"], snapshot, attestation),
            )
        )
        connection.execute(reports.insert().values(**row))
        connection.execute(
            n.report_evidence.insert().values(report_id=row["report_id"], snapshot=snapshot)
        )
        connection.execute(
            n.publication_attestations.insert().values(
                report_id=row["report_id"], attestation=attestation
            )
        )
    return ReportDocument(document)


def current_state(connection, document):
    """A read-only comparison. It cannot downgrade or authenticate frozen evidence."""
    identifier = document["provider"]["notification_id"]
    provider = provider_population(connection, identifier)
    try:
        execution, operations, _ = execution_evidence(connection, document["execution_id"])
        binding = document["execution_evidence"]
        operation = operations[binding["logical_operation_id"]]
        local = select_chain(connection, execution, operation, identifier, binding["operation_key"])
        snapshot = connection.scalar(
            sa.select(n.report_evidence.c.snapshot).filter_by(report_id=document["report_id"])
        )
        if (
            not provider["binding"]
            or not provider["request"]
            or local != snapshot["local"]
            or portable(dict(operation)) != snapshot["operation"]
            or any(provider[k] != snapshot["provider"][k] for k in ("binding", "request"))
            or provider_outcome(provider) == "contradictory"
        ):
            return "inconsistent"
        return "current" if provider == snapshot["provider"] else "historical"
    except (KeyError, TypeError, ValueError):
        return "inconsistent"
