from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise ValueError("agent migrations require the guarded execution store")
context.configure(
    connection=connection, version_table_schema="opsdesk_agent", transactional_ddl=True
)
with context.begin_transaction():
    context.run_migrations()
