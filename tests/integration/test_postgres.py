"""PostgreSQL lifecycle, integrity, authorization and transaction behavior."""

import copy
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema, DropSchema

from agent_reliability_lab.opsdesk import tables as t
from agent_reliability_lab.opsdesk.contracts import (
    ActorContext,
    CustomerOrders,
    DocumentSearch,
    Lookup,
    ServiceError,
    TaskCreate,
    TaskList,
    TaskPatch,
    TaskUpdate,
)
from agent_reliability_lab.opsdesk.database import schema_for
from agent_reliability_lab.opsdesk.fixtures import (
    from_scenario,
    load_baseline,
    load_scenario,
)
from agent_reliability_lab.opsdesk.services import OpsDeskService

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]
VIEWER = ActorContext(actor_id="viewer_001", tenant_id="opsdesk")
SUPPORT = ActorContext(actor_id="support_001", tenant_id="opsdesk")
SUPERVISOR = ActorContext(actor_id="supervisor_001", tenant_id="opsdesk")


def create_request(key="create_01", title="Synthetic follow-up") -> TaskCreate:
    return TaskCreate(customer_id="customer_001", title=title, idempotency_key=key)


def update_request(task_id="task_001", version=1, status="resolved", key="update_01") -> TaskUpdate:
    return TaskUpdate(
        task_id=task_id,
        expected_version=version,
        patch=TaskPatch(status=status),
        idempotency_key=key,
    )


def counts(sandbox) -> tuple[int, int, int]:
    with sandbox.transaction() as (connection, _):
        return tuple(
            connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            for table in (t.tasks, t.receipts, t.audit)
        )


def test_migrations_create_expected_postgres_schema(sandbox) -> None:
    sandbox.apply_migrations()
    with sandbox.transaction() as (connection, _):
        inspector = sa.inspect(connection)
        assert set(inspector.get_table_names(schema=sandbox.schema)) == {
            "tenants",
            "actors",
            "customers",
            "orders",
            "payments",
            "accounts",
            "tasks",
            "documents",
            "sandbox_identity",
            "write_receipts",
            "mutation_audit",
            "alembic_version",
        }
        version = sa.Table(
            "alembic_version", sa.MetaData(), schema=sandbox.schema, autoload_with=connection
        )
        assert connection.execute(sa.select(version.c.version_num)).scalar_one() == "0001_opsdesk"
        indexes = inspector.get_indexes("documents", schema=sandbox.schema)
        assert any(
            item["name"] == "ix_documents_search"
            and item["dialect_options"]["postgresql_using"] == "gin"
            for item in indexes
        )
        assert (
            connection.execute(sa.select(sa.func.version())).scalar_one().startswith("PostgreSQL")
        )


def test_repeated_seeds_have_equal_logical_state(sandbox_factory) -> None:
    first, second = sandbox_factory(), sandbox_factory()
    assert first.schema != second.schema
    assert first.snapshot() == second.snapshot()
    assert first.verify() and second.verify()


@pytest.mark.parametrize(
    "path", sorted((ROOT / "benchmarks/development").glob("*.json")), ids=lambda path: path.stem
)
def test_all_legacy_scenarios_load_exact_initial_projection(path, sandbox_factory) -> None:
    scenario = load_scenario(path)
    sandbox = sandbox_factory(from_scenario(scenario), scenario.tools)
    expected = {}
    for name in ("documents", "customers", "orders", "payments", "accounts", "tasks"):
        records = getattr(scenario.fixture, name)
        expected[name] = {getattr(item, name[:-1] + "_id"): item.model_dump() for item in records}
    assert sandbox.snapshot(benchmark=True) == expected
    assert sandbox.verify()


def test_scenario_multistep_update_keeps_legacy_diff_contract(sandbox_factory) -> None:
    scenario = load_scenario(ROOT / "benchmarks/development/multi_step_resolve_task.json")
    sandbox = sandbox_factory(from_scenario(scenario), scenario.tools)
    actor = ActorContext(actor_id=scenario.actor.actor_id, tenant_id=scenario.actor.tenant_id)
    initial = sandbox.snapshot(benchmark=True)
    OpsDeskService(sandbox).update_task(actor, update_request())
    initial["tasks"]["task_001"].update(status="resolved", version=2)
    assert sandbox.snapshot(benchmark=True) == initial


def test_reads_are_authorized_and_use_exact_decimal(sandbox) -> None:
    service = OpsDeskService(sandbox)
    order = service.get_order(VIEWER, Lookup(record_id="order_001"))
    assert order.total_amount == Decimal("25.00")
    assert service.get_customer(VIEWER, Lookup(record_id="customer_001")).email.endswith(".invalid")
    orders = service.list_customer_orders(VIEWER, CustomerOrders(customer_id="customer_001"))
    assert [item.order_id for item in orders.items] == ["order_001", "order_002"]


@pytest.mark.parametrize(
    "actor",
    [
        ActorContext(actor_id="missing_actor", tenant_id="opsdesk"),
        ActorContext(actor_id="supervisor_001", tenant_id="otherdesk"),
    ],
)
def test_unknown_and_forged_tenant_actor_rejected(sandbox, actor) -> None:
    before = sandbox.snapshot()
    with pytest.raises(ServiceError) as caught:
        OpsDeskService(sandbox).create_task(actor, create_request())
    assert caught.value.detail.code == "unauthorized"
    assert sandbox.snapshot() == before


def test_cross_tenant_and_absent_records_are_indistinguishable(sandbox) -> None:
    service = OpsDeskService(sandbox)
    details = []
    for identifier in ("customer_other", "customer_absent"):
        with pytest.raises(ServiceError) as caught:
            service.get_customer(VIEWER, Lookup(record_id=identifier))
        details.append(caught.value.detail)
    assert details[0] == details[1]
    with pytest.raises(ServiceError, match="Record not found"):
        service.create_task(
            SUPPORT, TaskCreate(customer_id="customer_other", title="No", idempotency_key="x")
        )


def test_viewer_writes_denied_without_any_mutation(sandbox) -> None:
    service = OpsDeskService(sandbox)
    before = sandbox.snapshot()
    for request, method in [
        (create_request(), service.create_task),
        (update_request(), service.update_task),
    ]:
        with pytest.raises(ServiceError) as caught:
            method(VIEWER, request)
        assert caught.value.detail.code == "unauthorized"
    assert sandbox.snapshot() == before
    assert counts(sandbox) == (4, 0, 0)


def test_scenario_allowlist_and_approval_are_fail_closed(sandbox_factory) -> None:
    from agent_reliability_lab.opsdesk.fixtures import baseline_access

    access = baseline_access()
    access.permitted.remove("create_task")
    sandbox = sandbox_factory(access=access)
    with pytest.raises(ServiceError) as caught:
        OpsDeskService(sandbox).create_task(SUPERVISOR, create_request())
    assert caught.value.detail.code == "unauthorized"
    access = baseline_access()
    access.approval_required = ["create_task"]
    sandbox = sandbox_factory(access=access)
    with pytest.raises(ServiceError) as caught:
        OpsDeskService(sandbox).create_task(SUPERVISOR, create_request())
    assert caught.value.detail.code == "approval_required"
    assert counts(sandbox) == (4, 0, 0)


def test_authorized_create_update_and_audit(sandbox) -> None:
    service = OpsDeskService(sandbox)
    task = service.create_task(SUPPORT, create_request())
    changed = service.update_task(SUPPORT, update_request(task.task_id))
    assert changed.status == "resolved" and changed.version == 2
    assert changed.updated_at > task.updated_at
    assert counts(sandbox) == (5, 2, 2)


def test_only_supervisor_can_reopen(sandbox) -> None:
    service = OpsDeskService(sandbox)
    request = update_request("task_002", status="open")
    with pytest.raises(ServiceError) as caught:
        service.update_task(SUPPORT, request)
    assert caught.value.detail.code == "unauthorized"
    changed = service.update_task(SUPERVISOR, request)
    assert changed.status == "open"


def test_idempotent_create_update_and_conflicting_reuse(sandbox) -> None:
    service = OpsDeskService(sandbox)
    request = create_request()
    task = service.create_task(SUPPORT, request)
    assert service.create_task(SUPPORT, request) == task
    with pytest.raises(ServiceError) as caught:
        service.create_task(SUPPORT, create_request(title="Different"))
    assert caught.value.detail.code == "idempotency_conflict"
    update = update_request(task.task_id)
    result = service.update_task(SUPPORT, update)
    assert service.update_task(SUPPORT, update) == result
    assert counts(sandbox) == (5, 2, 2)


def test_retry_waits_for_uncommitted_receipt_then_reuses_it(sandbox, monkeypatch):
    service = OpsDeskService(sandbox)
    request = create_request()
    written = threading.Event()
    release = threading.Event()
    original = service._finish

    def hold_before_commit(*args):
        result = original(*args)
        written.set()
        assert release.wait(8)
        return result

    monkeypatch.setattr(service, "_finish", hold_before_commit)
    with ThreadPoolExecutor(max_workers=6) as pool:
        first = pool.submit(service.create_task, SUPPORT, request)
        assert written.wait(5)
        retries = [pool.submit(service.create_task, SUPPORT, request) for _ in range(5)]
        try:
            with sandbox.engine.connect() as connection:
                until = time.monotonic() + 5
                while time.monotonic() < until:
                    waiting = connection.scalar(
                        sa.text(
                            "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
                            "AND query LIKE :query"
                        ),
                        {"query": f"%{sandbox.schema}.sandbox_identity%FOR UPDATE%"},
                    )
                    if waiting:
                        break
                    connection.rollback()  # Statistics snapshots are transaction-scoped.
                    time.sleep(0.02)
                assert waiting > 0
        finally:
            release.set()
        assert all(retry.result() == first.result() for retry in retries)
    assert counts(sandbox) == (5, 1, 1)


def test_process_death_before_commit_allows_one_fresh_retry(sandbox):
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
import sys
from tests.integration.test_postgres import SUPPORT, create_request
from agent_reliability_lab.opsdesk.database import SandboxManager, engine_from_env
from agent_reliability_lab.opsdesk.services import OpsDeskService
service = OpsDeskService(SandboxManager(engine_from_env()).open(sys.argv[1]))
finish = service._finish
def exit_before_commit(*args):
    finish(*args)
    os._exit(29)
service._finish = exit_before_commit
service.create_task(SUPPORT, create_request())
""",
            sandbox.run_id,
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        timeout=20,
    )
    assert run.returncode == 29, run.stderr.decode()
    assert counts(sandbox) == (4, 0, 0)
    service = OpsDeskService(sandbox)
    assert service.create_task(SUPPORT, create_request()) == service.create_task(
        SUPPORT, create_request()
    )
    assert counts(sandbox) == (5, 1, 1)


def test_same_key_in_distinct_tenants_and_denied_replay(sandbox):
    with sandbox.transaction() as (connection, _):
        connection.execute(
            t.actors.update()
            .where(t.actors.c.actor_id == "viewer_other")
            .values(role="support_agent")
        )
    service = OpsDeskService(sandbox)
    other = ActorContext(actor_id="viewer_other", tenant_id="otherdesk")
    first = service.create_task(SUPPORT, create_request())
    request = TaskCreate(
        customer_id="customer_other", title="Other tenant", idempotency_key="create_01"
    )
    second = service.create_task(other, request)
    assert first.task_id != second.task_id
    assert service.create_task(other, request) == second
    with sandbox.transaction() as (connection, _):
        connection.execute(
            t.actors.update().where(t.actors.c.actor_id == other.actor_id).values(role="viewer")
        )
    with pytest.raises(ServiceError) as denied:
        service.create_task(other, request)
    assert denied.value.detail.code == "unauthorized"
    assert counts(sandbox) == (6, 2, 2)


def test_version_conflict_rolls_back(sandbox) -> None:
    service = OpsDeskService(sandbox)
    service.update_task(SUPPORT, update_request())
    before = sandbox.snapshot()
    with pytest.raises(ServiceError) as caught:
        service.update_task(SUPPORT, update_request(key="different_key"))
    assert caught.value.detail.code == "version_conflict"
    assert sandbox.snapshot() == before
    assert counts(sandbox) == (4, 1, 1)


def test_failure_after_domain_write_and_receipt_rolls_everything_back(sandbox, monkeypatch) -> None:
    service = OpsDeskService(sandbox)
    before = sandbox.snapshot()

    def failing_finish(connection, receipt, sequence, prior, after):
        connection.execute(
            t.receipts.insert().values(**receipt, response=after.model_dump(mode="json"))
        )
        connection.execute(
            t.audit.insert().values(
                sequence=sequence,
                tenant_id=SUPPORT.tenant_id,
                actor_id=SUPPORT.actor_id,
                operation="create_task",
                task_id="nonexistent_task",
                before=None,
                after={},
            )
        )

    monkeypatch.setattr(service, "_finish", failing_finish)
    with pytest.raises(ServiceError) as caught:
        service.create_task(SUPPORT, create_request())
    assert caught.value.detail.code == "constraint_violation"
    assert sandbox.snapshot() == before
    assert counts(sandbox) == (4, 0, 0)
    with sandbox.transaction() as (connection, _):
        assert connection.execute(sa.select(t.identity.c.mutation_sequence)).scalar_one() == 0


def test_constraints_and_foreign_keys_reject_invalid_data(sandbox) -> None:
    before = sandbox.snapshot()
    with pytest.raises(IntegrityError):
        with sandbox.transaction() as (connection, _):
            connection.execute(t.payments.update().values(order_id="missing_order"))
    with pytest.raises(IntegrityError):
        with sandbox.transaction() as (connection, _):
            connection.execute(t.orders.update().values(total_amount=Decimal("-1.00")))
    with pytest.raises(IntegrityError):
        with sandbox.transaction() as (connection, _):
            connection.execute(
                t.tasks.update().where(t.tasks.c.task_id == "task_001").values(order_id="order_003")
            )
    assert sandbox.snapshot() == before


def test_full_text_search_is_tenant_scoped_and_payload_is_inert(sandbox) -> None:
    service = OpsDeskService(sandbox)
    hits = service.search_documents(VIEWER, DocumentSearch(query="refund eligibility"))
    assert [item.document_id for item in hits.items] == ["refund_policy"]
    assert service.search_documents(VIEWER, DocumentSearch(query="absentword")).items == []
    before = sandbox.snapshot()
    document = service.get_document(VIEWER, Lookup(record_id="injection_memo"))
    assert "Ignore all previous instructions" in document.content
    assert document.trust_classification == "untrusted"
    assert sandbox.snapshot() == before
    # SQL punctuation is a bound search parameter, not executable SQL.
    service.search_documents(VIEWER, DocumentSearch(query="'; DROP TABLE tasks; --"))
    assert counts(sandbox) == (4, 0, 0)


def test_task_pagination_is_stable(sandbox) -> None:
    service = OpsDeskService(sandbox)
    first = service.list_tasks(VIEWER, TaskList(limit=2))
    second = service.list_tasks(VIEWER, TaskList(limit=2, after_id=first.next_after_id))
    assert [item.task_id for item in first.items + second.items] == [
        f"task_{i:03d}" for i in range(1, 5)
    ]
    assert second.next_after_id is None


def test_reset_restores_state_receipts_and_logical_clock(sandbox) -> None:
    initial = sandbox.snapshot()
    service = OpsDeskService(sandbox)
    first = service.create_task(SUPPORT, create_request())
    assert not sandbox.verify()
    sandbox.reset()
    assert sandbox.snapshot() == initial and sandbox.verify()
    assert counts(sandbox) == (4, 0, 0)
    assert service.create_task(SUPPORT, create_request()) == first
    sandbox.reset()
    sandbox.reset()
    assert sandbox.snapshot() == initial


def test_independent_runs_do_not_share_mutations(sandbox_factory) -> None:
    first, second = sandbox_factory(), sandbox_factory()
    initial = second.snapshot()
    OpsDeskService(first).create_task(SUPPORT, create_request())
    first.reset()
    assert second.snapshot() == initial


def test_concurrent_sandboxes_and_retry_writes(sandbox_factory) -> None:
    first, second = sandbox_factory(), sandbox_factory()
    barrier = threading.Barrier(4)

    def create(sandbox):
        barrier.wait(timeout=10)
        return OpsDeskService(sandbox).create_task(SUPPORT, create_request())

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create, [first, first, second, second]))
    assert all(item == results[0] for item in results)
    assert counts(first) == counts(second) == (5, 1, 1)


def test_concurrent_distinct_updates_use_optimistic_version(sandbox) -> None:
    barrier = threading.Barrier(2)

    def update(key):
        barrier.wait(timeout=10)
        try:
            return OpsDeskService(sandbox).update_task(SUPPORT, update_request(key=key)).version
        except ServiceError as error:
            return error.detail.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["race_one", "race_two"]))
    assert set(results) == {2, "version_conflict"}
    assert counts(sandbox) == (4, 1, 1)


def test_duplicate_provision_does_not_overwrite(sandbox, manager) -> None:
    from agent_reliability_lab.opsdesk.fixtures import baseline_access

    before = sandbox.snapshot()
    with pytest.raises(ValueError, match="already exists"):
        manager.provision(sandbox.run_id, load_baseline(), baseline_access())
    assert sandbox.snapshot() == before


def test_cleanup_only_registered_owned_namespace(sandbox, manager) -> None:
    # A plausible prefix alone never grants cleanup permission.
    name = "unregistered_01"
    with manager.engine.begin() as connection:
        connection.execute(CreateSchema(schema_for(name)))
    try:
        with pytest.raises(ValueError, match="not registered"):
            manager.cleanup(name)
        with manager.engine.connect() as connection:
            assert sa.inspect(connection).has_schema(schema_for(name))
        with pytest.raises(ValueError, match="run_id"):
            manager.cleanup("public; DROP SCHEMA public")
        manager.cleanup(sandbox.run_id)
        with manager.engine.connect() as connection:
            assert not sa.inspect(connection).has_schema(sandbox.schema)
            assert sa.inspect(connection).has_schema("public")
    finally:
        with manager.engine.begin() as connection:
            connection.execute(DropSchema(schema_for(name)))


def test_marker_mismatch_blocks_cleanup_and_reset(sandbox, manager) -> None:
    with sandbox.transaction() as (connection, _):
        original = connection.execute(sa.select(t.identity.c.marker)).scalar_one()
        connection.execute(t.identity.update().values(marker="mismatch"))
    try:
        for action in [sandbox.reset, lambda: manager.cleanup(sandbox.run_id)]:
            with pytest.raises(ValueError, match="marker mismatch"):
                action()
    finally:
        with manager.engine.begin() as connection:
            connection = connection.execution_options(
                schema_translate_map={t.DOMAIN_SCHEMA: sandbox.schema}
            )
            connection.execute(t.identity.update().values(marker=original))


def test_failed_provision_is_atomic(manager) -> None:
    from agent_reliability_lab.opsdesk.fixtures import baseline_access

    seed = copy.deepcopy(load_baseline())
    seed.customer_details["customer_002"] = seed.customer_details["customer_001"]
    name = "failed_provision"
    with pytest.raises(IntegrityError):
        manager.provision(name, seed, baseline_access())
    with manager.engine.connect() as connection:
        assert not sa.inspect(connection).has_schema(schema_for(name))
        assert (
            connection.execute(sa.select(t.registry).where(t.registry.c.run_id == name)).first()
            is None
        )


def test_seed_hash_tampering_blocks_reset(sandbox, manager) -> None:
    with manager.engine.begin() as connection:
        original = connection.execute(
            sa.select(t.registry.c.seed_hash).where(t.registry.c.run_id == sandbox.run_id)
        ).scalar_one()
        connection.execute(
            t.registry.update().where(t.registry.c.run_id == sandbox.run_id).values(seed_hash="bad")
        )
    try:
        with pytest.raises(ValueError, match="fixture hash mismatch"):
            sandbox.reset()
    finally:
        with manager.engine.begin() as connection:
            connection.execute(
                t.registry.update()
                .where(t.registry.c.run_id == sandbox.run_id)
                .values(seed_hash=original)
            )


def test_concurrent_provisioning_has_independent_migration_context(sandbox_factory) -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: sandbox_factory(), range(2)))
    assert first.verify() and second.verify()
    assert first.snapshot() == second.snapshot()


def test_cleanup_refuses_external_dependencies_atomically(sandbox, manager) -> None:
    from sqlalchemy.exc import DBAPIError

    before = sandbox.snapshot()
    view = "dependency_" + sandbox.run_id
    preparer = manager.engine.dialect.identifier_preparer
    view_name = "public." + preparer.quote(view)
    table_name = preparer.quote(sandbox.schema) + ".customers"
    with manager.engine.begin() as connection:
        connection.execute(sa.DDL(f"CREATE VIEW {view_name} AS SELECT * FROM {table_name}"))
    try:
        with pytest.raises(DBAPIError):
            manager.cleanup(sandbox.run_id)
        assert sandbox.snapshot() == before
        with manager.engine.connect() as connection:
            assert sa.inspect(connection).has_table(view, schema="public")
    finally:
        with manager.engine.begin() as connection:
            connection.execute(sa.DDL(f"DROP VIEW {view_name}"))


def test_failed_reset_rolls_back_deletes_and_reseeding(sandbox, manager) -> None:
    OpsDeskService(sandbox).create_task(SUPPORT, create_request())
    mutated = sandbox.snapshot()
    with manager.engine.begin() as connection:
        original = connection.execute(
            sa.select(t.registry.c.initial_hash).where(t.registry.c.run_id == sandbox.run_id)
        ).scalar_one()
        connection.execute(
            t.registry.update()
            .where(t.registry.c.run_id == sandbox.run_id)
            .values(initial_hash="intentional_bad_hash")
        )
    try:
        with pytest.raises(ValueError, match="reset did not restore"):
            sandbox.reset()
        assert sandbox.snapshot() == mutated
        assert counts(sandbox) == (5, 1, 1)
    finally:
        with manager.engine.begin() as connection:
            connection.execute(
                t.registry.update()
                .where(t.registry.c.run_id == sandbox.run_id)
                .values(initial_hash=original)
            )


def test_unsupported_transition_is_rejected_even_for_supervisor(sandbox) -> None:
    before = sandbox.snapshot()
    with pytest.raises(ServiceError) as caught:
        OpsDeskService(sandbox).update_task(SUPERVISOR, update_request("task_003", status="open"))
    assert caught.value.detail.code == "invalid_arguments"
    assert sandbox.snapshot() == before


def test_identical_arguments_with_independent_keys_are_separate_writes(sandbox):
    service = OpsDeskService(sandbox)
    first = service.create_task(SUPPORT, create_request(key="separate_a"))
    second = service.create_task(SUPPORT, create_request(key="separate_b"))
    assert first.task_id != second.task_id
    assert counts(sandbox) == (6, 2, 2)
