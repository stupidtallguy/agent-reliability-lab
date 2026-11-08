"""Guarded per-run PostgreSQL schemas and transaction-scoped lifecycle locks."""

import json
import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from agent_reliability_lab.benchmarks.scenario import ToolAccess
from agent_reliability_lab.opsdesk import tables as t
from agent_reliability_lab.opsdesk.fixtures import (
    SeedSpec,
    benchmark_state,
    digest,
    logical_state,
    populate,
)

ALLOWED_DATABASES = {"opsdesk_lab", "opsdesk_lab_test", "opsdesk_lab_ci"}
_MIGRATION_LOCK = Lock()  # Alembic's module-level context proxy is not thread-local.


def schema_for(run_id: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", run_id):
        raise ValueError(
            "run_id must be 2-32 lowercase letters/digits/underscores, starting with a letter"
        )
    return f"opsdesk_run_{run_id}"


def make_engine(url: str, *, allow_sandbox: bool = False) -> Engine:
    parsed = make_url(url)
    if not allow_sandbox:
        raise ValueError("set OPSDESK_ALLOW_SANDBOX=1 to enable sandbox administration")
    if parsed.drivername != "postgresql+psycopg" or parsed.database not in ALLOWED_DATABASES:
        raise ValueError(
            "only postgresql+psycopg and dedicated opsdesk_lab database names are allowed"
        )
    return sa.create_engine(
        parsed,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={
            "options": "-c timezone=UTC -c statement_timeout=15000 -c lock_timeout=10000"
        },
    )


def engine_from_env() -> Engine:
    url = os.environ.get("OPSDESK_DATABASE_URL")
    if not url:
        raise ValueError("OPSDESK_DATABASE_URL is required; credentials are never inferred")
    return make_engine(url, allow_sandbox=os.environ.get("OPSDESK_ALLOW_SANDBOX") == "1")


def lock(connection: Connection, name: str, *, shared: bool = False) -> None:
    function = sa.func.pg_advisory_xact_lock_shared if shared else sa.func.pg_advisory_xact_lock
    connection.execute(sa.select(function(sa.func.hashtextextended("opsdesk:" + name, 0))))


def migrate(connection: Connection, schema: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    config.attributes.update(connection=connection, sandbox_schema=schema)
    with _MIGRATION_LOCK:
        command.upgrade(config, "head")


class SandboxManager:
    def __init__(self, engine: Engine) -> None:
        # Validate even if a caller bypassed make_engine. No SQL happens before this check.
        if engine.dialect.name != "postgresql" or engine.url.database not in ALLOWED_DATABASES:
            raise ValueError("sandbox manager requires a dedicated OpsDesk PostgreSQL database")
        self.engine = engine

    def initialize(self) -> None:
        with self.engine.begin() as connection:
            lock(connection, "control")
            connection.execute(CreateSchema("opsdesk_control", if_not_exists=True))
            migrate(connection, "opsdesk_control")

    def provision(self, run_id: str, seed: SeedSpec, access: ToolAccess) -> "Sandbox":
        schema = schema_for(run_id)
        seed = SeedSpec.model_validate_json(seed.model_dump_json())
        access = ToolAccess.model_validate_json(access.model_dump_json())
        self.initialize()
        marker = str(uuid.uuid4())
        with self.engine.begin() as connection:
            lock(connection, run_id)
            if connection.execute(
                sa.select(t.registry.c.run_id).where(t.registry.c.run_id == run_id)
            ).first():
                raise ValueError("sandbox already exists; use reset rather than overwriting it")
            connection.execute(CreateSchema(schema))
            migrate(connection, schema)
            connection = connection.execution_options(
                schema_translate_map={t.DOMAIN_SCHEMA: schema}
            )
            connection.execute(
                t.identity.insert().values(
                    singleton=1, run_id=run_id, marker=marker, mutation_sequence=0
                )
            )
            populate(connection, seed)
            seed_data = seed.model_dump(mode="json")
            connection.execute(
                t.registry.insert().values(
                    run_id=run_id,
                    schema_name=schema,
                    marker=marker,
                    seed_spec=seed_data,
                    tool_access=access.model_dump(mode="json"),
                    seed_hash=digest(seed_data),
                    initial_hash=digest(logical_state(connection)),
                )
            )
        return self.open(run_id)

    def open(self, run_id: str) -> "Sandbox":
        return Sandbox(self.engine, run_id)

    def cleanup(self, run_id: str) -> None:
        sandbox = self.open(run_id)
        with sandbox.transaction(exclusive=True) as (connection, _):
            # RESTRICT throughout: external dependencies or unknown objects abort atomically.
            t.metadata.drop_all(connection, checkfirst=False)
            version = sa.Table("alembic_version", sa.MetaData(), schema=sandbox.schema)
            version.drop(connection)
            connection.execute(DropSchema(sandbox.schema))
            connection.execute(t.registry.delete().where(t.registry.c.run_id == run_id))


class Sandbox:
    def __init__(self, engine: Engine, run_id: str) -> None:
        self.engine = engine
        self.run_id = run_id
        self.schema = schema_for(run_id)
        if engine.dialect.name != "postgresql" or engine.url.database not in ALLOWED_DATABASES:
            raise ValueError("sandbox requires a dedicated OpsDesk PostgreSQL database")

    @contextmanager
    def transaction(self, *, exclusive: bool = False) -> Iterator[tuple[Connection, dict]]:
        with self.engine.begin() as connection:
            lock(connection, self.run_id, shared=not exclusive)
            row = (
                connection.execute(sa.select(t.registry).where(t.registry.c.run_id == self.run_id))
                .mappings()
                .first()
            )
            if row is None or row["schema_name"] != self.schema:
                raise ValueError("sandbox is not registered; refusing access or cleanup")
            connection = connection.execution_options(
                schema_translate_map={t.DOMAIN_SCHEMA: self.schema}
            )
            identity = connection.execute(sa.select(t.identity)).mappings().one()
            if identity["marker"] != row["marker"] or identity["run_id"] != self.run_id:
                raise ValueError("sandbox ownership marker mismatch; refusing operation")
            yield connection, dict(row)

    def snapshot(self, *, benchmark: bool = False) -> dict:
        # Exclusive lock prevents mutations between table reads at READ COMMITTED.
        with self.transaction(exclusive=True) as (connection, _):
            return benchmark_state(connection) if benchmark else logical_state(connection)

    def verify(self) -> bool:
        with self.transaction(exclusive=True) as (connection, row):
            if digest(row["seed_spec"]) != row["seed_hash"]:
                raise ValueError("stored fixture hash mismatch")
            return digest(logical_state(connection)) == row["initial_hash"]

    def reset(self) -> None:
        with self.transaction(exclusive=True) as (connection, row):
            if digest(row["seed_spec"]) != row["seed_hash"]:
                raise ValueError("stored fixture hash mismatch; refusing reset")
            seed = SeedSpec.model_validate_json(json.dumps(row["seed_spec"]))
            for table in [t.audit, t.receipts, *reversed(t.DOMAIN_TABLES)]:
                connection.execute(table.delete())
            connection.execute(t.identity.update().values(mutation_sequence=0))
            populate(connection, seed)
            if digest(logical_state(connection)) != row["initial_hash"]:
                raise ValueError("reset did not restore the original logical state; rolled back")

    def apply_migrations(self) -> None:
        with self.transaction(exclusive=True) as (connection, _):
            migrate(connection, self.schema)
