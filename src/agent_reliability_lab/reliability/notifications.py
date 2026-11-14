"""Synthetic-only notification intent, transactional outbox, and provider evidence."""

from typing import Annotated, Literal

import sqlalchemy as sa
from pydantic import Field
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.schema import CreateSchema

from agent_reliability_lab.benchmarks.scenario import Contract, Identifier
from agent_reliability_lab.opsdesk import tables as business
from agent_reliability_lab.opsdesk.contracts import ActorContext, ServiceError
from agent_reliability_lab.opsdesk.database import Sandbox, lock
from agent_reliability_lab.opsdesk.fixtures import digest

TOOL = "queue_notification"
SCHEMA = "opsdesk_reliability"
metadata = sa.MetaData(schema=SCHEMA)
text = sa.String(128)


class NotificationInput(Contract):
    customer_id: Identifier
    template: Literal["order_status", "support_update"]


class NotificationRequest(NotificationInput):
    idempotency_key: Annotated[str, Field(pattern=r"^mcp_[a-f0-9]{64}$")]


class LocalReceipt(NotificationInput):
    notification_id: str
    status: Literal["local_intent_recorded"] = "local_intent_recorded"


Fault = Literal["normal", "reject", "timeout_before_accept", "lose_ack"]
Delivery = Literal["pending", "delivered", "failed"]


def table(name, *columns):
    return sa.Table(name, metadata, *columns)


def key(name):
    return sa.Column(name, text, primary_key=True)


def field(name, kind=text):
    return sa.Column(name, kind, nullable=False)


def notification_key(target):
    return sa.Column(
        "notification_id",
        text,
        sa.ForeignKey(f"{SCHEMA}.{target}.notification_id"),
        primary_key=True,
    )


admissions = table("admissions", key("marker"), key("actor_id"), key("tenant_id"), field("run_id"))
intents = table(
    "intents",
    key("notification_id"),
    field("marker"),
    field("actor_id"),
    field("tenant_id"),
    field("run_id"),
    field("operation_key"),
    field("payload_hash"),
    field("receipt", JSONB),
    sa.UniqueConstraint("marker", "actor_id", "tenant_id", "operation_key"),
)
outbox = table("outbox", notification_key("intents"), field("payload_hash"))
provider = table(
    "provider",
    notification_key("outbox"),
    field("payload_hash"),
    field("status"),
    sa.CheckConstraint("status IN ('accepted', 'rejected')"),
)
acknowledgments = table("acknowledgments", notification_key("provider"))
delivery = table(
    "delivery",
    notification_key("provider"),
    key("event_id"),
    field("sequence", sa.Integer),
    field("status"),
    sa.CheckConstraint("sequence > 0"),
    sa.CheckConstraint("status IN ('pending', 'delivered', 'failed')"),
    sa.UniqueConstraint("notification_id", "sequence"),
)
# Additive storage. Legacy provider/callback rows are retained without invented bindings.
provider_bindings = table(
    "provider_bindings",
    notification_key("provider"),
    field("provider_operation_id"),
    field("status"),
    sa.UniqueConstraint("provider_operation_id"),
)
issued_events = table(
    "issued_events",
    key("event_id"),
    sa.Column(
        "provider_operation_id",
        text,
        sa.ForeignKey(f"{SCHEMA}.provider_bindings.provider_operation_id"),
        nullable=False,
    ),
    sa.Column(
        "notification_id", text, sa.ForeignKey(f"{SCHEMA}.provider.notification_id"), nullable=False
    ),
    field("sequence", sa.Integer),
    field("status"),
    field("payload_hash"),
    sa.UniqueConstraint("notification_id", "sequence"),
    sa.CheckConstraint("sequence > 0"),
    sa.CheckConstraint("status IN ('pending', 'delivered', 'failed')"),
)
callback_conflicts = table(
    "callback_conflicts",
    key("conflict_id"),
    field("notification_id"),
    field("event_id"),
    field("sequence", sa.Integer),
    field("status"),
    field("reason"),
)
intent_conflicts = table(
    "intent_conflicts",
    key("conflict_id"),
    sa.Column(
        "notification_id", text, sa.ForeignKey(f"{SCHEMA}.intents.notification_id"), nullable=False
    ),
    field("payload_hash"),
)
dispatches = table(
    "dispatches",
    notification_key("outbox"),
    sa.Column("sequence", sa.Integer, primary_key=True),
    field("fault"),
)
reports = table(
    "reports",
    key("report_id"),
    field("execution_id"),
    field("revision", sa.Integer),
    field("document", JSONB),
    sa.UniqueConstraint("execution_id", "revision"),
)


def lookup(connection, source, notification_id):
    return (
        connection.execute(sa.select(source).where(source.c.notification_id == notification_id))
        .mappings()
        .one_or_none()
    )


class NotificationLab:
    """Provisioning and provider controls belong to the synthetic host, never the model."""

    def __init__(self, sandbox: Sandbox):
        if not sandbox.run_id.startswith("rel_") or sandbox.engine.url.database not in {
            "opsdesk_lab_test",
            "opsdesk_lab_ci",
        }:
            raise ValueError("notifications require an explicitly registered reliability sandbox")
        self.sandbox = sandbox

    def register(self, actor: ActorContext) -> None:
        with self.sandbox.transaction() as (connection, registry):
            lock(connection, "reliability-schema")
            self._check_role(connection, actor)
            connection.execute(CreateSchema(SCHEMA, if_not_exists=True))
            metadata.create_all(connection)
            connection.exec_driver_sql("""
                CREATE OR REPLACE FUNCTION opsdesk_reliability.reject_report_change()
                RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                    RAISE EXCEPTION 'frozen reliability reports are append-only';
                END; $$
            """)
            connection.exec_driver_sql("""
                CREATE OR REPLACE TRIGGER frozen_reliability_report
                BEFORE UPDATE OR DELETE ON opsdesk_reliability.reports
                FOR EACH ROW EXECUTE FUNCTION opsdesk_reliability.reject_report_change()
            """)
            for source in (issued_events, callback_conflicts, delivery, intent_conflicts):
                connection.exec_driver_sql(f"""
                    CREATE OR REPLACE TRIGGER frozen_reliability_evidence
                    BEFORE UPDATE OR DELETE ON {source.fullname}
                    FOR EACH ROW EXECUTE FUNCTION opsdesk_reliability.reject_report_change()
                """)
            connection.execute(
                insert(admissions)
                .values(
                    marker=registry["marker"],
                    run_id=self.sandbox.run_id,
                    **actor.model_dump(),
                )
                .on_conflict_do_nothing()
            )

    @staticmethod
    def _check_role(connection, actor):
        # Serialize against concurrent role changes before any receipt is returned.
        role = connection.execute(
            sa.select(business.actors.c.role)
            .where(
                business.actors.c.actor_id == actor.actor_id,
                business.actors.c.tenant_id == actor.tenant_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if role not in {"support_agent", "supervisor"}:
            raise ServiceError("unauthorized", "Notification action is not permitted.")

    def queue(self, actor: ActorContext, request: NotificationRequest) -> LocalReceipt:
        with self.sandbox.transaction() as (connection, registry):
            self._check_role(connection, actor)
            if not connection.scalar(sa.select(sa.func.to_regclass(f"{SCHEMA}.admissions"))):
                raise ServiceError("unauthorized", "Reliability sandbox is not registered.")
            identity = dict(marker=registry["marker"], **actor.model_dump())
            allowed = connection.scalar(sa.select(admissions.c.run_id).filter_by(**identity))
            if allowed != self.sandbox.run_id:
                raise ServiceError("unauthorized", "Notification action is not permitted.")
            customer = connection.scalar(
                sa.select(business.customers.c.customer_id).where(
                    business.customers.c.customer_id == request.customer_id,
                    business.customers.c.tenant_id == actor.tenant_id,
                )
            )
            if customer is None:
                raise ServiceError("not_found", "Synthetic customer was not found.")
            clean = request.model_dump(exclude={"idempotency_key"})
            identifier = digest([identity, request.idempotency_key])
            fingerprint = digest(clean)
            previous = lookup(connection, intents, identifier)
            if previous:
                self._chain(connection, registry, identifier)
                if previous["payload_hash"] == fingerprint:
                    return LocalReceipt.model_validate(previous["receipt"])
                connection.execute(
                    insert(intent_conflicts)
                    .values(
                        conflict_id=digest([identifier, fingerprint]),
                        notification_id=identifier,
                        payload_hash=fingerprint,
                    )
                    .on_conflict_do_nothing()
                )
            else:
                receipt = LocalReceipt(notification_id=identifier, **clean)
                connection.execute(
                    intents.insert().values(
                        **identity,
                        notification_id=identifier,
                        payload_hash=fingerprint,
                        run_id=self.sandbox.run_id,
                        operation_key=request.idempotency_key,
                        receipt=receipt.model_dump(mode="json"),
                    )
                )
                connection.execute(
                    outbox.insert().values(
                        notification_id=identifier,
                        payload_hash=fingerprint,
                    )
                )
                return receipt
        raise ServiceError("idempotency_conflict", "Notification intent has changed.")

    def _owned(self, connection, registry, identifier):
        intent = lookup(connection, intents, identifier)
        if not intent or (intent["run_id"], intent["marker"]) != (
            self.sandbox.run_id,
            registry["marker"],
        ):
            raise ValueError("notification does not belong to this sandbox incarnation")
        return intent

    def _chain(self, connection, registry, identifier):
        """Validate the committed identity and all available provider-side joins."""
        intent = self._owned(connection, registry, identifier)
        identity = {key: intent[key] for key in ("marker", "actor_id", "tenant_id")}
        try:
            receipt = LocalReceipt.model_validate(intent["receipt"])
        except ValueError:
            raise ValueError("invalid_intent_receipt") from None
        payload = receipt.model_dump(include={"customer_id", "template"})
        operation_key = intent["operation_key"]
        if (
            receipt.notification_id != identifier
            or digest([identity, operation_key]) != identifier
            or digest(payload) != intent["payload_hash"]
            or connection.scalar(sa.select(admissions.c.run_id).filter_by(**identity))
            != self.sandbox.run_id
        ):
            raise ValueError("contradictory_intent_identity")
        message = lookup(connection, outbox, identifier)
        if not message:
            raise ValueError("missing_outbox")
        if message["payload_hash"] != intent["payload_hash"]:
            raise ValueError("contradictory_outbox_payload")
        effect = lookup(connection, provider, identifier)
        binding = lookup(connection, provider_bindings, identifier)
        operation = digest(
            ["synthetic-provider", identifier, operation_key, intent["payload_hash"]]
        )
        if effect:
            if effect["payload_hash"] != intent["payload_hash"]:
                raise ValueError("contradictory_provider_payload")
            if not binding:
                raise ValueError("missing_authoritative_provider_binding")
            if (
                binding["provider_operation_id"] != operation
                or binding["status"] != effect["status"]
            ):
                raise ValueError("contradictory_provider_operation")
        elif binding:
            raise ValueError("missing_provider_record")
        elif connection.scalar(
            sa.select(
                sa.exists().where(
                    dispatches.c.notification_id == identifier,
                    dispatches.c.fault != "timeout_before_accept",
                )
            )
        ):
            raise ValueError("missing_provider_record")
        return intent, effect, operation

    def dispatch(
        self,
        identifier: str,
        fault: Fault = "normal",
        *,
        payload_hash: str | None = None,
        after_provider_commit=None,
    ) -> str:
        if fault not in {"normal", "reject", "timeout_before_accept", "lose_ack"}:
            raise ValueError("unknown synthetic dispatch fault")
        # A separate transaction intentionally leaves a durable provider record if
        # the dispatcher dies before writing its local acknowledgment.
        with self.sandbox.transaction() as (connection, registry):
            lock(connection, "notification:" + identifier)
            intent, prior, operation = self._chain(connection, registry, identifier)
            if payload_hash is not None and payload_hash != intent["payload_hash"]:
                raise ServiceError("idempotency_conflict", "Provider payload has changed.")
            sequence = (
                connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(dispatches)
                    .where(dispatches.c.notification_id == identifier)
                )
                + 1
            )
            connection.execute(
                dispatches.insert().values(
                    notification_id=identifier,
                    sequence=sequence,
                    fault=fault,
                )
            )
            if fault == "timeout_before_accept" and not prior:
                return "timed_out"
            status = prior["status"] if prior else ("rejected" if fault == "reject" else "accepted")
            if not prior:
                connection.execute(
                    provider.insert().values(
                        notification_id=identifier,
                        payload_hash=intent["payload_hash"],
                        status=status,
                    )
                )
                connection.execute(
                    provider_bindings.insert().values(
                        notification_id=identifier,
                        provider_operation_id=operation,
                        status=status,
                    )
                )
        if after_provider_commit is not None:
            after_provider_commit()
        if fault == "lose_ack":
            return "acknowledgment_lost"
        with self.sandbox.transaction() as (connection, registry):
            lock(connection, "notification:" + identifier)
            self._chain(connection, registry, identifier)
            connection.execute(
                insert(acknowledgments)
                .values(
                    notification_id=identifier,
                )
                .on_conflict_do_nothing()
            )
        return status

    @staticmethod
    def _event_input(event_id, sequence, status):
        if not 1 <= sequence <= 2147483647 or not 1 <= len(event_id) <= 128:
            raise ValueError("invalid provider event identity")
        if status not in {"pending", "delivered", "failed"}:
            raise ValueError("invalid provider delivery state")

    @staticmethod
    def _record_conflict(connection, event, reason, authority=None):
        affected = {event["notification_id"]}
        if authority:
            affected.add(authority["notification_id"])
        for identifier in sorted(affected):
            connection.execute(
                insert(callback_conflicts)
                .values(
                    **{**event, "notification_id": identifier},
                    conflict_id=digest([identifier, event, reason]),
                    reason=reason,
                )
                .on_conflict_do_nothing()
            )

    def issue_event(self, identifier: str, sequence: int, status: Delivery) -> str:
        """Trusted provider simulator only. The consumer cannot mint an event."""
        with self.sandbox.transaction() as (connection, registry):
            lock(connection, "notification:" + identifier)
            intent, effect, operation = self._chain(connection, registry, identifier)
            if not effect or effect["status"] != "accepted":
                raise ValueError("delivery event requires provider acceptance")
            event_id = digest([operation, sequence, status])
            self._event_input(event_id, sequence, status)
            event = dict(
                notification_id=identifier, event_id=event_id, sequence=sequence, status=status
            )
            existing = (
                connection.execute(
                    sa.select(issued_events).filter_by(
                        notification_id=identifier, sequence=sequence
                    )
                )
                .mappings()
                .one_or_none()
            )
            collision = existing is not None and existing["event_id"] != event_id
            if collision:
                self._record_conflict(connection, event, "conflicting_provider_sequence", existing)
            elif not existing:
                connection.execute(
                    issued_events.insert().values(
                        **event,
                        provider_operation_id=operation,
                        payload_hash=intent["payload_hash"],
                    )
                )
        if collision:
            raise ValueError("conflicting provider event sequence")
        return event_id

    def callback(self, identifier: str, event_id: str, sequence: int, status: Delivery) -> None:
        self._event_input(event_id, sequence, status)
        event = dict(
            notification_id=identifier, event_id=event_id, sequence=sequence, status=status
        )
        failure = None
        with self.sandbox.transaction() as (connection, registry):
            self._owned(connection, registry, identifier)
            authority = (
                connection.execute(sa.select(issued_events).filter_by(event_id=event_id))
                .mappings()
                .one_or_none()
            )
            # A foreign-incarnation replay can taint the requested local
            # notification but cannot write evidence into another sandbox.
            related = authority
            if authority and authority["notification_id"] != identifier:
                origin = lookup(connection, intents, authority["notification_id"])
                if (
                    not origin
                    or origin["run_id"] != self.sandbox.run_id
                    or (origin["marker"] != registry["marker"])
                ):
                    related = None
            identifiers = {identifier}
            if related:
                identifiers.add(related["notification_id"])
            for affected in sorted(identifiers):
                lock(connection, "notification:" + affected)
            try:
                intent, effect, operation = self._chain(connection, registry, identifier)
                if not effect or effect["status"] != "accepted":
                    failure = "missing_provider_acceptance"
                elif not authority:
                    failure = "missing_authoritative_callback"
                elif (
                    any(authority[k] != v for k, v in event.items())
                    or authority["provider_operation_id"] != operation
                    or authority["payload_hash"] != intent["payload_hash"]
                    or digest([operation, sequence, status]) != event_id
                ):
                    failure = "contradictory_callback_identity"
            except ValueError as error:
                failure = str(error)
            if not failure:
                recorded = (
                    connection.execute(
                        sa.select(delivery).where(
                            delivery.c.notification_id == identifier,
                            sa.or_(
                                delivery.c.event_id == event_id, delivery.c.sequence == sequence
                            ),
                        )
                    )
                    .mappings()
                    .all()
                )
                if recorded and (len(recorded) != 1 or dict(recorded[0]) != event):
                    failure = "contradictory_recorded_callback"
            if failure:
                self._record_conflict(connection, event, failure, related)
            else:
                connection.execute(insert(delivery).values(**event).on_conflict_do_nothing())
        if failure:
            raise ValueError(f"conflicting delivery callback: {failure}")

    def evidence(self, identifier: str) -> dict:
        with self.sandbox.transaction() as (connection, registry):
            lock(connection, "notification:" + identifier)
            owner = lookup(connection, intents, identifier)
            if owner and (owner["run_id"], owner["marker"]) != (
                self.sandbox.run_id,
                registry["marker"],
            ):
                raise ValueError("notification does not belong to this sandbox incarnation")
            issue = None
            try:
                intent, effect, operation = self._chain(connection, registry, identifier)
            except ValueError as error:
                issue = str(error)
                intent = effect = operation = None
            ack = lookup(connection, acknowledgments, identifier)
            events = (
                connection.execute(
                    sa.select(delivery)
                    .where(
                        delivery.c.notification_id == identifier,
                    )
                    .order_by(delivery.c.sequence)
                )
                .mappings()
                .all()
            )
            attempts = (
                connection.execute(
                    sa.select(dispatches)
                    .where(
                        dispatches.c.notification_id == identifier,
                    )
                    .order_by(dispatches.c.sequence)
                )
                .mappings()
                .all()
            )
            rejected_intents = [
                dict(row)
                for row in connection.execute(
                    sa.select(intent_conflicts)
                    .filter_by(notification_id=identifier)
                    .order_by(intent_conflicts.c.conflict_id)
                ).mappings()
            ]
            authoritative = {
                row["event_id"]: row
                for row in connection.execute(
                    sa.select(issued_events).filter_by(notification_id=identifier)
                ).mappings()
            }
            conflicts = [
                dict(row)
                for row in connection.execute(
                    sa.select(callback_conflicts)
                    .filter_by(notification_id=identifier)
                    .order_by(callback_conflicts.c.conflict_id)
                ).mappings()
            ]
            if intent and any(
                (authority := authoritative.get(event["event_id"])) is None
                or any(authority[k] != v for k, v in event.items())
                or authority["provider_operation_id"] != operation
                or authority["payload_hash"] != intent["payload_hash"]
                or digest([operation, event["sequence"], event["status"]]) != event["event_id"]
                for event in events
            ):
                issue = "contradictory_delivery_provenance"
        terminal = {event["status"] for event in events if event["status"] != "pending"}
        outcome = "unknown"
        if conflicts or (issue and issue.startswith("contradictory")):
            outcome = "contradictory"
        elif issue or (events and (not effect or effect["status"] != "accepted")):
            outcome = "unknown"
        elif effect and effect["status"] == "rejected":
            outcome = "provider_rejected"
        elif len(terminal) == 1:
            outcome = terminal.pop()
        elif terminal:
            outcome = "contradictory"
        return {
            "notification_id": identifier,
            "local_intent": "recorded" if intent else "unverified",
            "provider_operation_id": operation if effect else None,
            "payload_hash": intent["payload_hash"] if intent else None,
            "integrity_issue": issue,
            "callback_conflicts": conflicts,
            "rejected_conflicting_intents": rejected_intents,
            "outbox": "acknowledged" if ack else "pending",
            "provider_attempts": [dict(row) for row in attempts],
            "provider": effect["status"] if effect else ("submitted" if attempts else None),
            "acknowledged": bool(ack),
            "delivery": outcome,
            "delivery_events": [dict(row) for row in events],
        }
