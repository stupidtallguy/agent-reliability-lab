from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise ValueError("evaluation migrations require a guarded store")
context.configure(
    connection=connection, version_table_schema="opsdesk_evaluation", transactional_ddl=True
)
with context.begin_transaction():
    context.run_migrations()
