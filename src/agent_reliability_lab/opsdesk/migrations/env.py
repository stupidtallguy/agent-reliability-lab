"""Only the guarded sandbox manager may supply a migration connection."""

from alembic import context

from agent_reliability_lab.opsdesk.database import schema_for

config = context.config
connection = config.attributes.get("connection")
schema = config.attributes.get("sandbox_schema", "")
if connection is None or not (schema == "opsdesk_control" or schema.startswith("opsdesk_run_")):
    raise ValueError("use opsdesk migrate; an authorized sandbox connection is required")
if schema != "opsdesk_control" and schema_for(schema.removeprefix("opsdesk_run_")) != schema:
    raise ValueError("invalid migration namespace")
context.configure(connection=connection, version_table_schema=schema, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
