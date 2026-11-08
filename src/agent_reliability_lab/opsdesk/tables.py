"""SQLAlchemy Core tables. All runtime names are explicitly schema-qualified."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.schema import SchemaItem

DOMAIN_SCHEMA = "sandbox"
metadata = sa.MetaData(schema=DOMAIN_SCHEMA)


def entity(name: str, identifier: str, *columns: SchemaItem) -> sa.Table:
    return sa.Table(
        name,
        metadata,
        sa.Column(identifier, sa.String(64), primary_key=True),
        sa.Column(
            "tenant_id", sa.String(64), sa.ForeignKey("sandbox.tenants.tenant_id"), nullable=False
        ),
        *columns,
        sa.UniqueConstraint("tenant_id", identifier),
    )


def relation(local: str, remote: str, remote_id: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", local], [f"sandbox.{remote}.tenant_id", f"sandbox.{remote}.{remote_id}"]
    )


tenants = sa.Table("tenants", metadata, sa.Column("tenant_id", sa.String(64), primary_key=True))
actors = entity(
    "actors",
    "actor_id",
    sa.Column("role", sa.String(32), nullable=False),
    sa.CheckConstraint("role IN ('viewer','support_agent','supervisor')"),
)
customers = entity(
    "customers",
    "customer_id",
    sa.Column("display_name", sa.String(200), nullable=False),
    sa.Column("email", sa.String(254), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("tenant_id", "email"),
    sa.CheckConstraint("version >= 1"),
)
orders = entity(
    "orders",
    "order_id",
    sa.Column("customer_id", sa.String(64), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
    sa.Column("currency", sa.String(3), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    relation("customer_id", "customers", "customer_id"),
    sa.UniqueConstraint("tenant_id", "order_id", "customer_id"),
    sa.CheckConstraint("status IN ('pending','paid','shipped','cancelled')"),
    sa.CheckConstraint("total_amount >= 0 AND version >= 1"),
    sa.CheckConstraint("currency ~ '^[A-Z]{3}$'"),
)
payments = entity(
    "payments",
    "payment_id",
    sa.Column("order_id", sa.String(64), nullable=False),
    sa.Column("amount", sa.Numeric(12, 2), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    relation("order_id", "orders", "order_id"),
    sa.CheckConstraint("amount >= 0"),
    sa.CheckConstraint("status IN ('pending','settled','failed')"),
)
accounts = entity(
    "accounts",
    "account_id",
    sa.Column("customer_id", sa.String(64), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    relation("customer_id", "customers", "customer_id"),
    sa.CheckConstraint("status IN ('active','suspended')"),
)
tasks = entity(
    "tasks",
    "task_id",
    sa.Column("customer_id", sa.String(64), nullable=False),
    sa.Column("order_id", sa.String(64)),
    sa.Column("assigned_actor_id", sa.String(64)),
    sa.Column("title", sa.String(200), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("priority", sa.String(16), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    relation("customer_id", "customers", "customer_id"),
    relation("assigned_actor_id", "actors", "actor_id"),
    sa.ForeignKeyConstraint(
        ["tenant_id", "order_id", "customer_id"],
        ["sandbox.orders.tenant_id", "sandbox.orders.order_id", "sandbox.orders.customer_id"],
    ),
    sa.CheckConstraint("status IN ('open','in_progress','resolved')"),
    sa.CheckConstraint("priority IN ('low','normal','high')"),
    sa.CheckConstraint("version >= 1 AND length(trim(title)) > 0"),
)
documents = entity(
    "documents",
    "document_id",
    sa.Column("title", sa.String(10000), nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("category", sa.String(64), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("trust_classification", sa.String(16), nullable=False),
    sa.Column(
        "search_vector",
        TSVECTOR,
        sa.Computed(
            "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(content, ''))",
            persisted=True,
        ),
    ),
    sa.CheckConstraint("version >= 1 AND trust_classification = 'untrusted'"),
)
identity = sa.Table(
    "sandbox_identity",
    metadata,
    sa.Column("singleton", sa.Integer, primary_key=True),
    sa.Column("run_id", sa.String(32), nullable=False),
    sa.Column("marker", sa.String(36), nullable=False),
    sa.Column("mutation_sequence", sa.Integer, nullable=False),
    sa.CheckConstraint("singleton = 1 AND mutation_sequence >= 0"),
)
receipts = sa.Table(
    "write_receipts",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("actor_id", sa.String(64), primary_key=True),
    sa.Column("operation", sa.String(32), primary_key=True),
    sa.Column("idempotency_key", sa.String(128), primary_key=True),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("response", JSONB, nullable=False),
    relation("actor_id", "actors", "actor_id"),
)
audit = sa.Table(
    "mutation_audit",
    metadata,
    sa.Column("sequence", sa.Integer, primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("actor_id", sa.String(64), nullable=False),
    sa.Column("operation", sa.String(32), nullable=False),
    sa.Column("task_id", sa.String(64), nullable=False),
    sa.Column("before", JSONB),
    sa.Column("after", JSONB, nullable=False),
    relation("actor_id", "actors", "actor_id"),
    relation("task_id", "tasks", "task_id"),
)

sa.Index("ix_documents_search", documents.c.search_vector, postgresql_using="gin")
sa.Index("ix_orders_customer", orders.c.tenant_id, orders.c.customer_id, orders.c.order_id)
sa.Index("ix_payments_order", payments.c.tenant_id, payments.c.order_id)
sa.Index("ix_tasks_customer", tasks.c.tenant_id, tasks.c.customer_id, tasks.c.task_id)
sa.Index("ix_tasks_status", tasks.c.tenant_id, tasks.c.status, tasks.c.task_id)

control_metadata = sa.MetaData(schema="opsdesk_control")
registry = sa.Table(
    "sandboxes",
    control_metadata,
    sa.Column("run_id", sa.String(32), primary_key=True),
    sa.Column("schema_name", sa.String(63), nullable=False, unique=True),
    sa.Column("marker", sa.String(36), nullable=False),
    sa.Column("seed_spec", JSONB, nullable=False),
    sa.Column("tool_access", JSONB, nullable=False),
    sa.Column("initial_hash", sa.String(64)),
    sa.Column("seed_hash", sa.String(64), nullable=False),
)

DOMAIN_TABLES = (tenants, actors, customers, orders, payments, accounts, tasks, documents)
