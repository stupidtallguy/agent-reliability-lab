"""Transactional capacity and physical request accounting for the offline CP15 pilot."""

import json
import os
from datetime import timedelta
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.schema import CreateSchema

from agent_reliability_lab.agent.errors import BudgetExceeded
from agent_reliability_lab.agent.journal import Redactor
from agent_reliability_lab.opsdesk.database import lock
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.pilot_contracts import PilotPlan, ProviderObservation

metadata = sa.MetaData(schema="opsdesk_pilot")
ledgers = sa.Table(
    "ledgers",
    metadata,
    sa.Column("ledger_id", sa.String(32), primary_key=True),
    sa.Column("scope", sa.String(128), nullable=False),
    sa.Column("plan_hash", sa.String(64), nullable=False),
    sa.Column("plan", JSONB, nullable=False),
    sa.Column("arms", JSONB, nullable=False),
    sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
    sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
    sa.Column("breached", sa.Boolean, nullable=False, server_default=sa.false()),
)
attempts = sa.Table(
    "attempts",
    metadata,
    sa.Column("attempt_id", sa.String(32), primary_key=True),
    sa.Column("ledger_id", sa.ForeignKey(ledgers.c.ledger_id), nullable=False, index=True),
    sa.Column("body", JSONB, nullable=False),
)
events = sa.Table(
    "events",
    metadata,
    sa.Column("ledger_id", sa.ForeignKey(ledgers.c.ledger_id), primary_key=True),
    sa.Column("sequence", sa.Integer, primary_key=True),
    sa.Column("attempt_id", sa.ForeignKey(attempts.c.attempt_id), nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("body", JSONB, nullable=False),
)


class PilotBudgetBroker:
    def __init__(self, engine, scope, plan, *, authorization=None):
        self.engine, self.scope = engine, scope
        self.ledger_id = plan.ledger_id
        self.plan_hash = digest(plan.model_dump(mode="json"))
        self.authorization = authorization

    def _authorize(self, connection, mode, request=None):
        if mode == "offline_fixture":
            if (
                self.authorization is not None
                or request is not None
                and request.authorization_hash is not None
            ):
                raise ValueError("offline ledger cannot consume provider authorization")
            return None
        from agent_reliability_lab.research.live import active_authorization

        authority = active_authorization(connection, self.scope, self.authorization, self.plan_hash)
        if request is not None and (
            request.authorization_hash != self.authorization.content_hash
            or request.wire_hash is None
        ):
            raise ValueError(
                "physical attempt does not pin the provider authorization and wire request"
            )
        return authority

    def _require_disposable(self):
        if os.environ.get("OPSDESK_TEST_OWNED") != "1" or self.engine.url.database not in {
            "opsdesk_lab_ci",
            "opsdesk_lab_test",
        }:
            raise ValueError("pilot requires an explicitly owned disposable test database")

    def initialize(self):
        self._require_disposable()
        with self.engine.begin() as connection:
            lock(connection, "pilot_schema_v1")
            connection.execute(CreateSchema(metadata.schema, if_not_exists=True))
            metadata.create_all(connection)
            connection.execute(
                sa.text("""
                CREATE OR REPLACE FUNCTION opsdesk_pilot.reject_event_changes()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'frozen pilot budget event' USING ERRCODE='55000';
                END $$
            """)
            )
            connection.execute(
                sa.text("""
                CREATE OR REPLACE TRIGGER immutable_budget_event
                BEFORE UPDATE OR DELETE ON opsdesk_pilot.events
                FOR EACH ROW EXECUTE FUNCTION opsdesk_pilot.reject_event_changes()
            """)
            )

    def open(self, plan, arms):
        self._require_disposable()
        body = plan.model_dump(mode="json")
        if digest(body) != self.plan_hash:
            raise ValueError("pilot plan differs from ledger")
        inventory = {f"{a.slot}:{a.arm}": a.model_dump(mode="json") for a in arms}
        if not inventory or len(inventory) != len(arms):
            raise ValueError("pilot requires unique allocated arms")
        with self.engine.begin() as connection:
            authority = self._authorize(connection, plan.mode)
            now = self._now(connection)
            price = plan.pricing.prices[0]
            deadline = now + timedelta(seconds=plan.limits.duration_seconds)
            if authority is not None:
                deadline = min(deadline, authority.deadline)
            if now < price.effective_from or (
                price.effective_until is not None and deadline >= price.effective_until
            ):
                raise ValueError("frozen price is inapplicable to the pilot window")
            created = connection.execute(
                insert(ledgers)
                .values(
                    ledger_id=self.ledger_id,
                    scope=self.scope,
                    plan=body,
                    plan_hash=self.plan_hash,
                    arms=inventory,
                    deadline=deadline,
                )
                .on_conflict_do_nothing()
                .returning(ledgers.c.ledger_id)
            ).scalar_one_or_none()
            if created is None:
                raise ValueError("pilot ledger was already opened")

    @staticmethod
    def _now(connection):
        return connection.scalar(sa.select(sa.func.clock_timestamp()))

    def _ledger(self, connection, *, writing=True):
        query = sa.select(ledgers).where(ledgers.c.ledger_id == self.ledger_id)
        if writing:
            self._require_disposable()
            query = query.with_for_update()
        row = connection.execute(query).mappings().one_or_none()
        if row is None or (row["scope"], row["plan_hash"]) != (self.scope, self.plan_hash):
            raise ValueError("unknown or conflicting pilot ledger identity")
        if digest(row["plan"]) != self.plan_hash:
            raise ValueError("pilot ledger plan integrity mismatch")
        return row

    def _admit(self, connection, ledger):
        if ledger["breached"]:
            raise BudgetExceeded("pilot_provider_bound_breach")
        remaining = (ledger["deadline"] - self._now(connection)).total_seconds()
        if remaining <= 0:
            raise BudgetExceeded("pilot_experiment_deadline")
        return remaining

    def _attempt(self, connection, attempt_id):
        return (
            connection.execute(sa.select(attempts).where(attempts.c.attempt_id == attempt_id))
            .mappings()
            .one_or_none()
        )

    def _owned(self, connection, request):
        row = self._attempt(connection, request.attempt_id)
        if (
            row is None
            or row["ledger_id"] != self.ledger_id
            or row["body"]["request"] != request.model_dump(mode="json")
        ):
            raise ValueError("unknown or conflicting physical provider attempt")
        return row["body"]

    def _record(self, connection, attempt_id, kind, body):
        sequence = connection.scalar(
            ledgers.update()
            .where(ledgers.c.ledger_id == self.ledger_id)
            .values(sequence=ledgers.c.sequence + 1)
            .returning(ledgers.c.sequence)
        )
        connection.execute(
            events.insert().values(
                ledger_id=self.ledger_id,
                sequence=sequence,
                attempt_id=attempt_id,
                kind=kind,
                recorded_at=self._now(connection),
                body=body,
            )
        )

    def _change(self, connection, request, kind, body):
        connection.execute(
            attempts.update().where(attempts.c.attempt_id == request.attempt_id).values(body=body)
        )
        self._record(connection, request.attempt_id, kind, body)

    def reserve(self, request):
        submitted = request.model_dump(mode="json")
        with self.engine.begin() as connection:
            mode = self._ledger(connection, writing=False)["plan"]["mode"]
            self._authorize(connection, mode, request)
            ledger = self._ledger(connection)
            existing = self._attempt(connection, request.attempt_id)
            if existing is not None:
                return self._owned(connection, request)
            self._admit(connection, ledger)
            plan = PilotPlan.model_validate_json(json.dumps(ledger["plan"]))
            limits = plan.limits
            arm = request.allocation
            if (
                ledger["arms"].get(f"{arm.slot}:{arm.arm}") != submitted["allocation"]
                or request.pricing_hash != plan.pricing_hash
                or request.model_config_hash != digest(plan.model.model_dump(mode="json"))
                or request.maximum_output_tokens != arm.maximum_output_tokens
            ):
                raise ValueError("request differs from frozen pilot allocation, model or pricing")
            if (
                request.maximum_output_tokens > limits.maximum_output_tokens
                or request.estimated_input_tokens > limits.maximum_input_tokens
            ):
                raise BudgetExceeded("pilot_per_request_tokens")
            rows = connection.scalars(
                sa.select(attempts.c.body).where(attempts.c.ledger_id == self.ledger_id)
            ).all()
            active = [row for row in rows if row["state"] != "cancelled"]
            same_turn = [
                item
                for item in active
                if item["request"]["execution_id"] == request.execution_id
                and item["request"]["turn"] == request.turn
            ]
            _validate_retry(request, same_turn, limits.retries_per_turn)
            if (
                request.retry_of is not None
                and sum(item["request"]["retry_of"] is not None for item in active)
                >= limits.total_retries
            ):
                raise BudgetExceeded("pilot_total_retries")
            if (
                len(active) >= limits.total_calls
                or sum(item["request"]["allocation"]["scenario"] == arm.scenario for item in active)
                >= limits.calls_per_scenario
            ):
                raise BudgetExceeded("pilot_provider_calls")
            reserved_tokens = limits.maximum_input_tokens + request.maximum_output_tokens
            reserved_usd = plan.price_ceiling(
                limits.maximum_input_tokens, request.maximum_output_tokens
            )
            if (
                sum(item["charged_tokens"] for item in active) + reserved_tokens
                > limits.total_tokens
            ):
                raise BudgetExceeded("pilot_total_tokens")
            if (
                sum((Decimal(item["charged_usd"]) for item in active), reserved_usd)
                > limits.maximum_usd
            ):
                raise BudgetExceeded("pilot_usd")
            body = dict(
                request=submitted,
                state="reserved",
                reserved_input_tokens=limits.maximum_input_tokens,
                reserved_tokens=reserved_tokens,
                reserved_usd=str(reserved_usd),
                charged_tokens=reserved_tokens,
                charged_usd=str(reserved_usd),
                observation=None,
            )
            stored = connection.execute(
                insert(attempts)
                .values(attempt_id=request.attempt_id, ledger_id=self.ledger_id, body=body)
                .on_conflict_do_nothing()
                .returning(attempts.c.attempt_id)
            ).scalar_one_or_none()
            if stored is None:
                raise ValueError("physical provider attempt belongs to a different pilot ledger")
            self._record(connection, request.attempt_id, "reserved", body)
            return body

    def begin_dispatch(self, request):
        """Commit the sole dispatch permit and return the remaining experiment seconds."""
        with self.engine.begin() as connection:
            mode = self._ledger(connection, writing=False)["plan"]["mode"]
            self._authorize(connection, mode, request)
            ledger = self._ledger(connection)
            body = self._owned(connection, request)
            if body["state"] != "reserved":
                return None
            remaining = self._admit(connection, ledger)
            self._change(connection, request, "dispatched", body | {"state": "dispatched"})
            return remaining

    def cancel_pending(self, request):
        with self.engine.begin() as connection:
            self._ledger(connection)
            body = self._owned(connection, request)
            if body["state"] != "reserved":
                return False
            self._change(connection, request, "cancelled", body | {"state": "cancelled"})
            return True

    def mark_uncertain(self, request, *, reason=None):
        with self.engine.begin() as connection:
            self._ledger(connection)
            body = self._owned(connection, request)
            if body["state"] == "dispatched":
                body = body | {"state": "uncertain"}
                if reason is not None:
                    body["uncertain_reason"] = reason
                self._change(connection, request, "uncertain", body)

    def observe(self, request, observation: ProviderObservation):
        """Reconcile a reply, including billable failures, without refunding unknown usage."""
        observed = observation.model_dump(mode="json")
        if any(
            Redactor().text(value) != value
            for value in (
                observation.reported_model,
                observation.provider_request_id,
            )
            if value is not None
        ):
            raise ValueError("sensitive provider metadata rejected")
        with self.engine.begin() as connection:
            ledger = self._ledger(connection)
            body = self._owned(connection, request)
            if body["state"] in {"reserved", "cancelled"}:
                raise ValueError("provider usage requires a durably dispatched attempt")
            previous = body["observation"]
            if previous == observed:
                return body
            if previous is not None and any(
                observed.get(key) != value for key, value in previous.items() if value is not None
            ):
                raise ValueError("conflicting provider observation for this attempt")
            plan = PilotPlan.model_validate_json(json.dumps(ledger["plan"]))
            inputs, outputs = observation.input_tokens, observation.output_tokens
            billed = observation.billed_usd
            complete = inputs is not None and outputs is not None
            priced = plan.price_ceiling(inputs, outputs) if complete else None
            amount = max(priced, billed or Decimal(0)) if complete else billed
            model_mismatch = observation.reported_model != plan.model.model_id
            total = observation.reported_total_tokens
            breach = (
                body["state"] == "breached"
                or (inputs is not None and inputs > body["reserved_input_tokens"])
                or (outputs is not None and outputs > request.maximum_output_tokens)
                or (amount is not None and amount > Decimal(body["reserved_usd"]))
                or (observation.reported_model is not None and model_mismatch)
                or plan.mode == "future_live_requested"
                and (
                    bool(observation.cache_write_tokens)
                    or observation.unpriced_usage is True
                    or inputs is not None
                    and (observation.cached_input_tokens or 0) > inputs
                    or total is not None
                    and (total > body["reserved_tokens"] or complete and total != inputs + outputs)
                )
            )
            body = body | {"observation": observed, "state": "observed"}
            self._change(connection, request, "observed", body)
            if breach:
                connection.execute(
                    ledgers.update()
                    .where(ledgers.c.ledger_id == self.ledger_id)
                    .values(breached=True)
                )
                body = body | dict(
                    state="breached",
                    charged_tokens=max(
                        body["reserved_tokens"],
                        body["charged_tokens"],
                        (inputs or 0) + (outputs or 0),
                        total or 0,
                    ),
                    charged_usd=str(
                        max(
                            Decimal(body["reserved_usd"]),
                            Decimal(body["charged_usd"]),
                            amount or Decimal(0),
                        )
                    ),
                )
                self._change(connection, request, "breached", body)
            elif complete and not model_mismatch and observation.invalid_metering is None:
                body = body | dict(
                    state="settled",
                    charged_tokens=inputs + outputs,
                    charged_usd=str(amount),
                    cost_basis="provider_billed_or_upper_estimate"
                    if billed is not None
                    else "upper_estimate",
                )
                self._change(connection, request, "settled", body)
            return body

    def snapshot(self, count=None):
        """Reconstruct an immutable event prefix for report verification after reconciliation."""
        with self.engine.connect() as connection:
            ledger = self._ledger(connection, writing=False)
            limit = ledger["sequence"] if count is None else count
            if limit < 0 or limit > ledger["sequence"]:
                raise ValueError("invalid pilot event boundary")
            rows = [
                dict(row) | {"recorded_at": row["recorded_at"].isoformat()}
                for row in connection.execute(
                    sa.select(events)
                    .where(events.c.ledger_id == self.ledger_id, events.c.sequence <= limit)
                    .order_by(events.c.sequence)
                ).mappings()
            ]
            if [row["sequence"] for row in rows] != list(range(1, limit + 1)):
                raise ValueError("missing pilot event history")
            return rows


def _validate_retry(request, same_turn, maximum):
    if not same_turn and request.retry_of is None:
        return
    previous = next(
        (row for row in same_turn if row["request"]["attempt_id"] == request.retry_of), None
    )
    if previous is None or previous["state"] not in {"uncertain", "observed", "settled"}:
        raise ValueError(
            "retry must reference an earlier dispatched attempt with unresolved or failed outcome"
        )
    prior = previous["request"]
    if (
        previous["observation"] is not None
        and previous["observation"]["outcome"] != "failed"
        or any(item["request"]["retry_of"] == request.retry_of for item in same_turn)
        or any(
            prior[key] != request.model_dump(mode="json")[key]
            for key in (
                "allocation",
                "input_hash",
                "model_config_hash",
                "pricing_hash",
                "maximum_output_tokens",
            )
        )
    ):
        raise ValueError("retry conflicts with the physical request lineage")
    if len(same_turn) > maximum:
        raise BudgetExceeded("pilot_provider_retries")
