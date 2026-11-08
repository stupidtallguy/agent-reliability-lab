"""Eight narrow internal operations with shared authorization and atomic writes."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError

from agent_reliability_lab.opsdesk import tables as t
from agent_reliability_lab.opsdesk.contracts import (
    ActorContext,
    CustomerOrders,
    CustomerView,
    DocumentHit,
    DocumentSearch,
    DocumentView,
    Lookup,
    OrderView,
    Page,
    PageInput,
    ServiceError,
    TaskCreate,
    TaskList,
    TaskUpdate,
    TaskView,
)
from agent_reliability_lab.opsdesk.database import Sandbox
from agent_reliability_lab.opsdesk.fixtures import MUTATION_EPOCH, digest

READS = frozenset(
    {
        "search_documents",
        "get_document",
        "get_order",
        "get_customer",
        "list_customer_orders",
        "list_tasks",
    }
)
WRITES = frozenset({"create_task", "update_task"})


class OpsDeskService:
    """The trusted caller supplies identity; requested roles are never accepted."""

    def __init__(self, sandbox: Sandbox) -> None:
        self.sandbox = sandbox

    @contextmanager
    def _operation(self, actor: ActorContext, operation: str) -> Iterator[tuple[Connection, str]]:
        try:
            with self.sandbox.transaction() as (connection, registry):
                role = connection.execute(
                    sa.select(t.actors.c.role).where(
                        t.actors.c.actor_id == actor.actor_id,
                        t.actors.c.tenant_id == actor.tenant_id,
                    )
                ).scalar_one_or_none()
                access = registry["tool_access"]
                permitted = operation in access["available"] and operation in access["permitted"]
                role_allowed = (
                    operation in READS
                    and role in {"viewer", "support_agent", "supervisor"}
                    or operation in WRITES
                    and role in {"support_agent", "supervisor"}
                )
                if not permitted or not role_allowed:
                    raise ServiceError("unauthorized", "Operation is not permitted for this actor.")
                if operation in access.get("approval_required", []):
                    raise ServiceError("approval_required", "This operation requires approval.")
                yield connection, role
        except IntegrityError:
            raise ServiceError(
                "constraint_violation", "The write violates a data constraint."
            ) from None
        except DBAPIError as error:
            state = getattr(error.orig, "sqlstate", None)
            raise ServiceError(
                "storage_failure",
                "The sandbox operation could not complete.",
                retryable=state in {"40001", "40P01", "55P03", "57014"},
            ) from None

    @staticmethod
    def _record(connection: Connection, table: sa.Table, key: str, actor: ActorContext) -> dict:
        identifier = list(table.primary_key.columns)[0]
        row = (
            connection.execute(
                sa.select(table).where(identifier == key, table.c.tenant_id == actor.tenant_id)
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ServiceError("not_found", "Record not found.")
        return dict(row)

    @staticmethod
    def _page(
        connection: Connection,
        statement: sa.Select,
        identifier: sa.Column,
        request: PageInput,
        model: type,
    ) -> Page:
        if request.after_id is not None:
            statement = statement.where(identifier > request.after_id)
        rows = connection.execute(
            statement.order_by(identifier).limit(request.limit + 1)
        ).mappings()
        items = [model.model_validate(dict(row)) for row in rows]
        more = len(items) > request.limit
        items = items[: request.limit]
        return Page(
            items=items, next_after_id=getattr(items[-1], identifier.name) if more else None
        )

    def get_customer(self, actor: ActorContext, request: Lookup) -> CustomerView:
        with self._operation(actor, "get_customer") as (connection, _):
            record = self._record(connection, t.customers, request.record_id, actor)
            record.pop("tenant_id")
            return CustomerView.model_validate(record)

    def get_order(self, actor: ActorContext, request: Lookup) -> OrderView:
        with self._operation(actor, "get_order") as (connection, _):
            record = self._record(connection, t.orders, request.record_id, actor)
            record.pop("tenant_id")
            return OrderView.model_validate(record)

    def get_document(self, actor: ActorContext, request: Lookup) -> DocumentView:
        with self._operation(actor, "get_document") as (connection, _):
            record = self._record(connection, t.documents, request.record_id, actor)
            record.pop("tenant_id")
            record.pop("search_vector")
            return DocumentView.model_validate(record)

    def list_customer_orders(self, actor: ActorContext, request: CustomerOrders) -> Page[OrderView]:
        with self._operation(actor, "list_customer_orders") as (connection, _):
            self._record(connection, t.customers, request.customer_id, actor)
            columns = [column for column in t.orders.c if column.name != "tenant_id"]
            statement = sa.select(*columns).where(
                t.orders.c.tenant_id == actor.tenant_id,
                t.orders.c.customer_id == request.customer_id,
            )
            return self._page(connection, statement, t.orders.c.order_id, request, OrderView)

    def list_tasks(self, actor: ActorContext, request: TaskList) -> Page[TaskView]:
        with self._operation(actor, "list_tasks") as (connection, _):
            columns = [column for column in t.tasks.c if column.name != "tenant_id"]
            statement = sa.select(*columns).where(t.tasks.c.tenant_id == actor.tenant_id)
            if request.customer_id is not None:
                self._record(connection, t.customers, request.customer_id, actor)
                statement = statement.where(t.tasks.c.customer_id == request.customer_id)
            if request.status is not None:
                statement = statement.where(t.tasks.c.status == request.status)
            return self._page(connection, statement, t.tasks.c.task_id, request, TaskView)

    def search_documents(self, actor: ActorContext, request: DocumentSearch) -> Page[DocumentHit]:
        with self._operation(actor, "search_documents") as (connection, _):
            query = sa.func.plainto_tsquery(sa.literal_column("'english'"), request.query)
            statement = sa.select(
                t.documents.c.document_id,
                t.documents.c.title,
                sa.func.left(t.documents.c.content, 300).label("snippet"),
                t.documents.c.version,
            ).where(
                t.documents.c.tenant_id == actor.tenant_id,
                t.documents.c.search_vector.op("@@")(query),
            )
            return self._page(
                connection, statement, t.documents.c.document_id, request, DocumentHit
            )

    @staticmethod
    def _receipt(
        connection: Connection,
        actor: ActorContext,
        operation: str,
        request: TaskCreate | TaskUpdate,
    ) -> tuple[dict, TaskView | None]:
        # One row lock serializes writes in this sandbox; different runs remain independent.
        connection.execute(sa.select(t.identity).with_for_update()).one()
        key = dict(
            tenant_id=actor.tenant_id,
            actor_id=actor.actor_id,
            operation=operation,
            idempotency_key=request.idempotency_key,
        )
        request_hash = digest(request.model_dump(mode="json", exclude={"idempotency_key"}))
        row = (
            connection.execute(
                sa.select(t.receipts).where(
                    *(t.receipts.c[name] == value for name, value in key.items())
                )
            )
            .mappings()
            .first()
        )
        if row:
            if row["request_hash"] != request_hash:
                raise ServiceError(
                    "idempotency_conflict", "Key was already used for different arguments."
                )
            return {}, TaskView.model_validate_json(json.dumps(row["response"]))
        return {**key, "request_hash": request_hash}, None

    @staticmethod
    def _next_sequence(connection: Connection) -> int:
        return connection.execute(
            t.identity.update()
            .values(mutation_sequence=t.identity.c.mutation_sequence + 1)
            .returning(t.identity.c.mutation_sequence)
        ).scalar_one()

    @staticmethod
    def _finish(
        connection: Connection,
        receipt: dict,
        sequence: int,
        before: TaskView | None,
        after: TaskView,
    ) -> TaskView:
        payload = after.model_dump(mode="json")
        connection.execute(t.receipts.insert().values(**receipt, response=payload))
        connection.execute(
            t.audit.insert().values(
                sequence=sequence,
                tenant_id=receipt["tenant_id"],
                actor_id=receipt["actor_id"],
                operation=receipt["operation"],
                task_id=after.task_id,
                before=before.model_dump(mode="json") if before else None,
                after=payload,
            )
        )
        return after

    def create_task(self, actor: ActorContext, request: TaskCreate) -> TaskView:
        with self._operation(actor, "create_task") as (connection, _):
            receipt, replay = self._receipt(connection, actor, "create_task", request)
            if replay is not None:
                return replay
            self._record(connection, t.customers, request.customer_id, actor)
            sequence = self._next_sequence(connection)
            task_id = (
                "task_"
                + hashlib.sha256(
                    json.dumps(
                        [actor.tenant_id, actor.actor_id, "create_task", request.idempotency_key],
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()[:32]
            )
            moment = MUTATION_EPOCH + timedelta(seconds=sequence)
            data = dict(
                task_id=task_id,
                customer_id=request.customer_id,
                title=request.title,
                description="",
                status="open",
                priority="normal",
                assigned_actor_id=None,
                order_id=None,
                version=1,
                created_at=moment,
                updated_at=moment,
            )
            connection.execute(t.tasks.insert().values(tenant_id=actor.tenant_id, **data))
            return self._finish(connection, receipt, sequence, None, TaskView.model_validate(data))

    def update_task(self, actor: ActorContext, request: TaskUpdate) -> TaskView:
        with self._operation(actor, "update_task") as (connection, role):
            receipt, replay = self._receipt(connection, actor, "update_task", request)
            if replay is not None:
                return replay
            record = self._record(connection, t.tasks, request.task_id, actor)
            record.pop("tenant_id")
            before = TaskView.model_validate(record)
            if before.version != request.expected_version:
                raise ServiceError(
                    "version_conflict", "Task version has changed; read before retrying."
                )
            patch = request.patch.model_dump(exclude_unset=True)
            next_status = patch.get("status", before.status)
            allowed = {("open", "in_progress"), ("open", "resolved"), ("in_progress", "resolved")}
            if before.status != next_status and (before.status, next_status) not in allowed:
                if before.status != "resolved":
                    raise ServiceError(
                        "invalid_arguments", "This task transition is not supported."
                    )
                if role != "supervisor":
                    raise ServiceError(
                        "unauthorized", "This task transition requires a supervisor."
                    )
            sequence = self._next_sequence(connection)
            changes = {
                **patch,
                "version": before.version + 1,
                "updated_at": MUTATION_EPOCH + timedelta(seconds=sequence),
            }
            changed = connection.execute(
                t.tasks.update()
                .where(
                    t.tasks.c.task_id == request.task_id,
                    t.tasks.c.tenant_id == actor.tenant_id,
                    t.tasks.c.version == request.expected_version,
                )
                .values(**changes)
            )
            if changed.rowcount != 1:
                raise ServiceError("version_conflict", "Task version has changed.")
            return self._finish(
                connection,
                receipt,
                sequence,
                before,
                TaskView.model_validate({**record, **changes}),
            )
