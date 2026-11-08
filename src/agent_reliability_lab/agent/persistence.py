"""Transactional journal/intents plus the official PostgreSQL graph checkpointer."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from sqlalchemy.engine import Connection as SQLConnection
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateSchema

from agent_reliability_lab.agent import tables as t
from agent_reliability_lab.agent.config import AgentConfig, ModelConfig
from agent_reliability_lab.agent.errors import BudgetExceeded, ExecutionBusy
from agent_reliability_lab.agent.journal import EVENTS, Redactor
from agent_reliability_lab.agent.state import AgentResult, Decision, ModelCall
from agent_reliability_lab.opsdesk.database import _MIGRATION_LOCK, SandboxManager
from agent_reliability_lab.opsdesk.fixtures import digest


def utcnow() -> datetime:
    return datetime.now(UTC)


class JSONSerializer:
    """Only JSON values, with no pickle or arbitrary Python class reconstruction."""

    def dumps_typed(self, value):
        if isinstance(value, BaseException):
            value = {"safe_exception_type": type(value).__name__}
        return "json", json.dumps(value, ensure_ascii=False, allow_nan=False).encode()

    def loads_typed(self, value):
        kind, data = value
        if kind != "json":
            raise ValueError("unsupported checkpoint encoding")
        return json.loads(data)


class ThreadedPostgresSaver(PostgresSaver):
    """Official sync saver in workers: compatible with Windows MCP subprocesses."""

    async def aget_tuple(self, config):
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        items = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for item in items:
            yield item

    async def adelete_thread(self, thread_id):
        await asyncio.to_thread(self.delete_thread, thread_id)


class ExecutionStore:
    def __init__(self, engine: Engine, redactor: Redactor | None = None) -> None:
        SandboxManager(engine)  # Dedicated database guard, without modifying business state.
        self.engine = engine
        self.redactor = redactor or Redactor()

    @asynccontextmanager
    async def checkpointer(self) -> AsyncIterator[ThreadedPostgresSaver]:
        connection = await asyncio.to_thread(
            Connection.connect,
            self._conninfo(),
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        try:
            yield ThreadedPostgresSaver(connection, serde=JSONSerializer())
        finally:
            await asyncio.to_thread(connection.close)

    def _conninfo(self) -> str:
        url = self.engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
        return make_conninfo(url, options="-c search_path=opsdesk_agent_checkpoints,pg_catalog")

    async def initialize(self) -> None:
        # The advisory lock can wait. Never block this event loop while another
        # initializer needs it to finish setup and release the same lock.
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock:
            lock.execute(
                sa.select(
                    sa.func.pg_advisory_lock(sa.func.hashtextextended("opsdesk-agent-init", 0))
                )
            )
            try:
                with self.engine.begin() as connection:
                    connection.execute(CreateSchema("opsdesk_agent", if_not_exists=True))
                    connection.execute(
                        CreateSchema("opsdesk_agent_checkpoints", if_not_exists=True)
                    )
                    config = Config()
                    config.set_main_option(
                        "script_location", str(Path(__file__).with_name("migrations"))
                    )
                    config.attributes["connection"] = connection
                    with _MIGRATION_LOCK:
                        command.upgrade(config, "head")
                with Connection.connect(
                    self._conninfo(), autocommit=True, prepare_threshold=0, row_factory=dict_row
                ) as connection:
                    ThreadedPostgresSaver(connection, serde=JSONSerializer()).setup()
            finally:
                lock.execute(
                    sa.select(
                        sa.func.pg_advisory_unlock(
                            sa.func.hashtextextended("opsdesk-agent-init", 0)
                        )
                    )
                )

    @contextmanager
    def claim(self, execution_id: str) -> Iterator[None]:
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            key = "opsdesk-agent-execution:" + execution_id
            acquired = connection.execute(
                sa.select(sa.func.pg_try_advisory_lock(sa.func.hashtextextended(key, 0)))
            ).scalar_one()
            if not acquired:
                raise ExecutionBusy("execution is already active")
            try:
                yield
            finally:
                connection.execute(
                    sa.select(sa.func.pg_advisory_unlock(sa.func.hashtextextended(key, 0)))
                )

    def get(self, execution_id: str) -> dict:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(t.executions).where(t.executions.c.execution_id == execution_id)
                )
                .mappings()
                .one()
            )
            return dict(row)

    def create(self, config: AgentConfig, context: dict, task: str) -> str:
        execution_id, thread_id = uuid.uuid4().hex, uuid.uuid4().hex
        settings = config.model_dump(mode="json")
        if self.redactor.clean(settings) != settings:
            raise ValueError("sensitive configuration cannot be persisted")
        now = utcnow()
        with self.engine.begin() as connection:
            connection.execute(
                t.executions.insert().values(
                    execution_id=execution_id,
                    thread_id=thread_id,
                    config=settings,
                    config_hash=digest(settings),
                    context=context,
                    task=self.redactor.text(task),
                    status="prepared",
                    created_at=now,
                    updated_at=now,
                    deadline=now + timedelta(seconds=config.budgets.max_wall_seconds),
                    elapsed_ms=0.0,
                    timing_complete=True,
                    llm_calls=0,
                    tool_calls=0,
                    graph_steps=0,
                    journal_seq=0,
                )
            )
        return execution_id

    def update(self, execution_id: str, **values) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                t.executions.update()
                .where(t.executions.c.execution_id == execution_id)
                .values(**values, updated_at=utcnow())
            )

    def _event(
        self,
        connection: SQLConnection,
        execution_id: str,
        event_type: str,
        elapsed_ms: float,
        **payload,
    ) -> None:
        if event_type not in EVENTS:
            raise ValueError("unknown journal event type")
        sequence = connection.execute(
            t.executions.update()
            .where(t.executions.c.execution_id == execution_id)
            .values(
                journal_seq=t.executions.c.journal_seq + 1,
                elapsed_ms=elapsed_ms,
                updated_at=utcnow(),
            )
            .returning(t.executions.c.journal_seq)
        ).scalar_one()
        connection.execute(
            t.events.insert().values(
                execution_id=execution_id,
                sequence=sequence,
                event_type=event_type,
                timestamp=utcnow(),
                elapsed_ms=elapsed_ms,
                payload={
                    "schema_version": "1.0",
                    "correlation_id": execution_id,
                    **self.redactor.clean(payload),
                },
            )
        )

    def event(self, execution_id: str, event_type: str, elapsed_ms: float, **payload) -> None:
        with self.engine.begin() as connection:
            self._event(connection, execution_id, event_type, elapsed_ms, **payload)

    def finish_run(self, result: AgentResult) -> None:
        """Terminal metadata and its event commit together, after graph persistence."""
        with self.engine.begin() as connection:
            connection.execute(
                t.executions.update()
                .where(t.executions.c.execution_id == result.execution_id)
                .values(
                    status=result.status,
                    result=result.model_dump(mode="json"),
                    elapsed_ms=result.duration_seconds * 1000,
                    checkpoint_id=result.checkpoint_id,
                    updated_at=utcnow(),
                )
            )
            self._event(
                connection,
                result.execution_id,
                "run_interrupted"
                if result.resume_eligible
                else "run_completed"
                if result.status == "completed"
                else "run_failed",
                result.duration_seconds * 1000,
                status=result.status,
                reason=result.reason,
                response_completed=result.response_completed,
                agent_declared_completion=result.agent_declared_completion,
            )

    def reserve(self, execution_id: str, counter: str, maximum: int, elapsed_ms: float) -> int:
        with self.engine.begin() as connection:
            value = connection.execute(
                t.executions.update()
                .where(
                    t.executions.c.execution_id == execution_id, t.executions.c[counter] < maximum
                )
                .values(
                    {
                        counter: t.executions.c[counter] + 1,
                        "elapsed_ms": elapsed_ms,
                        "updated_at": utcnow(),
                    }
                )
                .returning(t.executions.c[counter])
            ).scalar_one_or_none()
            if value is None:
                raise BudgetExceeded(counter)
            return value

    def cached_reply(self, execution_id: str, turn: int) -> dict | None:
        with self.engine.connect() as connection:
            return connection.execute(
                sa.select(t.requests.c.reply).where(
                    t.requests.c.execution_id == execution_id,
                    t.requests.c.turn == turn,
                    t.requests.c.status == "completed",
                )
            ).scalar_one_or_none()

    def model_started(
        self,
        execution_id: str,
        turn: int,
        elapsed_ms: float,
        model: ModelConfig,
        maximum: int,
        input_hash: str,
    ) -> str:
        request_id = uuid.uuid4().hex
        with self.engine.begin() as connection:
            reserved = connection.execute(
                t.executions.update()
                .where(
                    t.executions.c.execution_id == execution_id, t.executions.c.llm_calls < maximum
                )
                .values(llm_calls=t.executions.c.llm_calls + 1)
                .returning(t.executions.c.llm_calls)
            ).scalar_one_or_none()
            if reserved is None:
                raise BudgetExceeded("llm_calls")
            connection.execute(
                t.requests.insert().values(
                    request_id=request_id, execution_id=execution_id, turn=turn, status="started"
                )
            )
            self._event(
                connection,
                execution_id,
                "model_request",
                elapsed_ms,
                request_id=request_id,
                turn=turn,
                provider=model.provider,
                model=model.model_id,
                input_hash=input_hash,
            )
        return request_id

    def model_finished(
        self,
        execution_id: str,
        request_id: str,
        reply: Decision,
        elapsed_ms: float,
        duration_ms: float,
    ) -> dict:
        safe = self.redactor.clean(reply.model_dump(mode="json"))
        with self.engine.begin() as connection:
            connection.execute(
                t.requests.update()
                .where(t.requests.c.request_id == request_id)
                .values(reply=safe, status="completed", duration_ms=duration_ms)
            )
            self._event(
                connection,
                execution_id,
                "model_response",
                elapsed_ms,
                request_id=request_id,
                usage=safe["usage"],
                reported_model=safe["reported_model"],
                provider_request_id=safe["provider_request_id"],
                call_count=len(safe["calls"]),
                answer=self.redactor.capture(safe["answer"]),
                duration_ms=duration_ms,
            )
        return safe

    def operation(self, proposal_id: str) -> dict:
        with self.engine.connect() as connection:
            return dict(
                connection.execute(
                    sa.select(t.operations).where(t.operations.c.proposal_id == proposal_id)
                )
                .mappings()
                .one()
            )

    def propose(
        self,
        execution_id: str,
        turn: int,
        position: int,
        call: ModelCall,
        arguments: dict,
        rejection: dict | None,
        elapsed_ms: float,
    ) -> str:
        proposal_id = uuid.uuid5(uuid.UUID(execution_id), f"{turn}:{position}").hex
        operation_id = (
            uuid.uuid5(uuid.UUID(proposal_id), "write").hex
            if call.name in {"create_task", "update_task"}
            else None
        )
        safe_arguments = self.redactor.clean(arguments)
        fingerprint = digest(safe_arguments)
        with self.engine.begin() as connection:
            existing = (
                connection.execute(
                    sa.select(t.operations).where(t.operations.c.proposal_id == proposal_id)
                )
                .mappings()
                .first()
            )
            if existing:
                if existing["arguments_hash"] != fingerprint or existing["tool"] != call.name:
                    raise ValueError("operation identity arguments conflict")
                return proposal_id
            connection.execute(
                t.operations.insert().values(
                    proposal_id=proposal_id,
                    execution_id=execution_id,
                    turn=turn,
                    position=position,
                    tool=self.redactor.text(call.name)[:128],
                    model_call_id=self.redactor.text(call.call_id),
                    operation_id=operation_id,
                    arguments=safe_arguments,
                    arguments_hash=fingerprint,
                    status="rejected" if rejection else "prepared",
                    response=rejection,
                )
            )
            self._event(
                connection,
                execution_id,
                "tool_call_proposed",
                elapsed_ms,
                tool_call_id=proposal_id,
                logical_operation_id=operation_id,
                tool=call.name,
                arguments_hash=fingerprint,
                arguments=self.redactor.capture(safe_arguments),
            )
            if rejection:
                self._event(
                    connection,
                    execution_id,
                    "tool_call_rejected",
                    elapsed_ms,
                    tool_call_id=proposal_id,
                    logical_operation_id=operation_id,
                    error_code=rejection["error"]["code"],
                    effect="not_dispatched",
                )
        return proposal_id

    def begin_attempt(
        self, execution_id: str, operation: dict, elapsed_ms: float, max_retries: int, maximum: int
    ) -> tuple[str, int] | None:
        attempt_id = uuid.uuid4().hex
        with self.engine.begin() as connection:
            count = connection.execute(
                sa.select(sa.func.count())
                .select_from(t.attempts)
                .where(t.attempts.c.proposal_id == operation["proposal_id"])
            ).scalar_one()
            if count >= max_retries + 1:
                return None
            reserved = connection.execute(
                t.executions.update()
                .where(
                    t.executions.c.execution_id == execution_id, t.executions.c.tool_calls < maximum
                )
                .values(tool_calls=t.executions.c.tool_calls + 1)
                .returning(t.executions.c.tool_calls)
            ).scalar_one_or_none()
            if reserved is None:
                raise BudgetExceeded("tool_calls")
            connection.execute(
                t.attempts.insert().values(
                    attempt_id=attempt_id,
                    proposal_id=operation["proposal_id"],
                    ordinal=count + 1,
                    status="started",
                    started_at=utcnow(),
                    effect="unknown",
                )
            )
            connection.execute(
                t.operations.update()
                .where(t.operations.c.proposal_id == operation["proposal_id"])
                .values(status="started")
            )
            self._event(
                connection,
                execution_id,
                "tool_call_started",
                elapsed_ms,
                tool_call_id=operation["proposal_id"],
                attempt_id=attempt_id,
                logical_operation_id=operation["operation_id"],
                tool=operation["tool"],
                ordinal=count + 1,
            )
        return attempt_id, count + 1

    def finish_attempt(
        self, execution_id, operation, attempt_id, response, retry, elapsed_ms, duration_ms, effect
    ):
        error = response.get("error")
        with self.engine.begin() as connection:
            connection.execute(
                t.attempts.update()
                .where(t.attempts.c.attempt_id == attempt_id)
                .values(
                    status="failed" if error else "succeeded",
                    error_code=error["code"] if error else None,
                    duration_ms=duration_ms,
                    effect=effect,
                )
            )
            connection.execute(
                t.operations.update()
                .where(t.operations.c.proposal_id == operation["proposal_id"])
                .values(
                    status="retry" if retry else "failed" if error else "succeeded",
                    response=response,
                )
            )
            self._event(
                connection,
                execution_id,
                "tool_call_failed" if error else "tool_call_succeeded",
                elapsed_ms,
                tool_call_id=operation["proposal_id"],
                attempt_id=attempt_id,
                logical_operation_id=operation["operation_id"],
                tool=operation["tool"],
                error_code=error["code"] if error else None,
                effect=effect,
                duration_ms=duration_ms,
                result=self.redactor.capture(response),
                response_hash=digest(response),
            )
            if retry:
                self._event(
                    connection,
                    execution_id,
                    "retry_scheduled",
                    elapsed_ms,
                    tool_call_id=operation["proposal_id"],
                    logical_operation_id=operation["operation_id"],
                    error_code=error["code"],
                )

    def trace(self, execution_id: str) -> list[dict]:
        with self.engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    sa.select(t.events)
                    .where(t.events.c.execution_id == execution_id)
                    .order_by(t.events.c.sequence)
                ).mappings()
            ]

    def usage(self, execution_id: str) -> dict:
        with self.engine.connect() as connection:
            rows = list(
                connection.execute(
                    sa.select(t.requests.c.reply).where(t.requests.c.execution_id == execution_id)
                ).scalars()
            )
        result = {
            "request_count": len(rows),
            "reported_count": sum(
                row is not None and row["usage"]["source"] != "unavailable" for row in rows
            ),
        }
        for name in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens"):
            values = [row["usage"][name] if row else None for row in rows]
            result[name] = sum(values) if all(value is not None for value in values) else None
        return result
