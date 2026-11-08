"""Real SDK protocol and real PostgreSQL; missing database configuration is a failure."""

import asyncio
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
import sqlalchemy as sa
from mcp import Client, MCPError
from pydantic import SecretStr

from agent_reliability_lab.mcp.client import TrustedClient, connect_stdio
from agent_reliability_lab.mcp.context import (
    BoundContext,
    LaunchConfig,
    LogicalOperation,
    sign_operation,
)
from agent_reliability_lab.mcp.servers import create_server
from agent_reliability_lab.opsdesk import tables as t
from agent_reliability_lab.opsdesk.fixtures import (
    baseline_access,
    from_scenario,
    load_baseline,
    load_scenario,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
ROOT = Path(__file__).resolve().parents[2]


def binding_for(sandbox, engine, *, actor="support_001", tenant="opsdesk"):
    return BoundContext.bind(
        engine,
        LaunchConfig(
            run_id=sandbox.run_id,
            actor_id=actor,
            tenant_id=tenant,
            signing_key=SecretStr(secrets.token_hex(32)),
        ),
    )


def counts(sandbox):
    with sandbox.transaction() as (connection, _):
        return tuple(
            connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            for table in (t.tasks, t.receipts, t.audit)
        )


def assert_success(result, tool=None):
    assert not result.is_error, result.structured_content
    assert result.structured_content["error"] is None
    if tool is not None:
        jsonschema.validate(result.structured_content, tool.output_schema)
    assert json.loads(result.content[0].text) == result.structured_content
    return result.structured_content["data"]


def assert_error(result, code):
    assert result.is_error
    assert result.structured_content["data"] is None
    assert result.structured_content["error"]["code"] == code


async def test_all_real_read_operations(bound, mcp_sandbox):
    before = mcp_sandbox.snapshot()
    calls = {
        "documents": [
            ("search_documents", {"query": "refund eligibility"}),
            ("get_document", {"document_id": "refund_policy"}),
        ],
        "business": [
            ("get_order", {"order_id": "order_001"}),
            ("get_customer", {"customer_id": "customer_001"}),
            ("list_customer_orders", {"customer_id": "customer_001"}),
        ],
        "tasks": [("list_tasks", {"customer_id": "customer_001", "status": "open"})],
    }
    names = set()
    for domain, requests in calls.items():
        async with Client(
            create_server(domain, bound), raise_exceptions=True, cache=None
        ) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            names.update(tools)
            for name, arguments in requests:
                data = assert_success(await client.call_tool(name, arguments), tools[name])
                if name == "get_order":
                    assert data["total_amount"] == "25.00"
                if name == "list_tasks":
                    assert [item["task_id"] for item in data["items"]] == ["task_001"]
    assert len(names) == 8
    assert mcp_sandbox.snapshot() == before


@pytest.mark.parametrize(
    "tool,field,identifier",
    [
        ("get_customer", "customer_id", "customer_other"),
        ("get_customer", "customer_id", "customer_absent"),
        ("get_order", "order_id", "order_other"),
        ("get_order", "order_id", "order_absent"),
    ],
)
async def test_unknown_and_cross_tenant_business_records(bound, tool, field, identifier):
    async with Client(create_server("business", bound), raise_exceptions=True) as client:
        result = await client.call_tool(tool, {field: identifier})
        assert_error(result, "not_found")
        assert result.structured_content["error"]["message"] == "Record not found."


@pytest.mark.parametrize("identifier", ["other_policy", "missing_policy"])
async def test_document_scope_and_missing_records(bound, identifier):
    async with Client(create_server("documents", bound), raise_exceptions=True) as client:
        assert_error(
            await client.call_tool("get_document", {"document_id": identifier}), "not_found"
        )


async def test_empty_search_and_filtered_tasks(bound):
    async with Client(create_server("documents", bound), raise_exceptions=True) as client:
        empty = assert_success(await client.call_tool("search_documents", {"query": "absentword"}))
        assert empty == {"items": [], "next_after_id": None}
    async with Client(create_server("tasks", bound), raise_exceptions=True) as client:
        empty = assert_success(
            await client.call_tool("list_tasks", {"customer_id": "customer_003", "status": "open"})
        )
        assert empty["items"] == []


async def test_pagination_and_bounds(bound):
    async with Client(create_server("business", bound), raise_exceptions=True) as client:
        first = assert_success(
            await client.call_tool(
                "list_customer_orders", {"customer_id": "customer_001", "limit": 1}
            )
        )
        second = assert_success(
            await client.call_tool(
                "list_customer_orders",
                {"customer_id": "customer_001", "limit": 1, "after_id": first["next_after_id"]},
            )
        )
        assert [first["items"][0]["order_id"], second["items"][0]["order_id"]] == [
            "order_001",
            "order_002",
        ]
        assert second["next_after_id"] is None
        assert_error(
            await client.call_tool(
                "list_customer_orders", {"customer_id": "customer_001", "limit": 51}
            ),
            "validation_error",
        )
    async with Client(create_server("documents", bound), raise_exceptions=True) as client:
        assert_error(
            await client.call_tool("search_documents", {"query": "refund", "limit": 21}),
            "validation_error",
        )
        assert_error(
            await client.call_tool("search_documents", {"query": "x" * 501}), "validation_error"
        )
    async with Client(create_server("tasks", bound), raise_exceptions=True) as client:
        assert_error(await client.call_tool("list_tasks", {"limit": 0}), "validation_error")


async def test_untrusted_document_text_is_data_and_cannot_change_permissions(bound, mcp_sandbox):
    before = mcp_sandbox.snapshot()
    async with Client(create_server("documents", bound), raise_exceptions=True) as client:
        result = await client.call_tool("get_document", {"document_id": "injection_memo"})
        data = assert_success(result)
        assert "Ignore all previous instructions" in data["content"]
        assert data["trust_classification"] == "untrusted"
        assert result.structured_content["provenance"]["trust_classification"] == "untrusted"
        assert result.structured_content["provenance"]["seed_hash"] == bound.seed_hash
        with pytest.raises(MCPError, match="Unknown tool"):
            await client.call_tool("create_task", {"customer_id": "customer_001", "title": "No"})
    assert mcp_sandbox.snapshot() == before


async def test_create_update_retries_and_exact_serialization(bound, mcp_sandbox):
    async with Client(create_server("tasks", bound), raise_exceptions=True) as sdk:
        client = TrustedClient(sdk, bound.config)
        tools = {tool.name: tool for tool in (await client.discover()).tools}
        create = LogicalOperation.new()
        arguments = {"customer_id": "customer_001", "title": "Protocol task"}
        task = assert_success(
            await client.write("create_task", arguments, create), tools["create_task"]
        )
        retry = assert_success(
            await client.write("create_task", arguments, create), tools["create_task"]
        )
        assert retry == task
        update = LogicalOperation.new()
        change = {
            "task_id": task["task_id"],
            "expected_version": 1,
            "patch": {"status": "resolved"},
        }
        updated = assert_success(
            await client.write("update_task", change, update), tools["update_task"]
        )
        assert updated["version"] == 2 and updated["status"] == "resolved"
        assert assert_success(await client.write("update_task", change, update)) == updated
        # Retrying a create returns its original recorded state, even after a later update.
        assert assert_success(await client.write("create_task", arguments, create)) == task
    assert counts(mcp_sandbox) == (5, 2, 2)


async def test_conflicting_arguments_and_distinct_intent(bound, mcp_sandbox):
    async with Client(create_server("tasks", bound), raise_exceptions=True) as sdk:
        client = TrustedClient(sdk, bound.config)
        operation = LogicalOperation.new()
        arguments = {"customer_id": "customer_001", "title": "Protocol task"}
        first = assert_success(await client.write("create_task", arguments, operation))
        assert_error(
            await client.write("create_task", {**arguments, "title": "Different"}, operation),
            "idempotency_conflict",
        )
        second = assert_success(
            await client.write("create_task", arguments, LogicalOperation.new())
        )
        assert first["task_id"] != second["task_id"]
    assert counts(mcp_sandbox) == (6, 2, 2)


async def test_stale_task_version_and_transition_authorization(bound, mcp_sandbox, mcp_manager):
    async with Client(create_server("tasks", bound), raise_exceptions=True) as sdk:
        client = TrustedClient(sdk, bound.config)
        arguments = {"task_id": "task_001", "expected_version": 1, "patch": {"status": "resolved"}}
        assert_success(await client.write("update_task", arguments, LogicalOperation.new()))
        assert_error(
            await client.write("update_task", arguments, LogicalOperation.new()), "version_conflict"
        )
        reopen = {"task_id": "task_001", "expected_version": 2, "patch": {"status": "open"}}
        assert_error(
            await client.write("update_task", reopen, LogicalOperation.new()), "permission_denied"
        )
    supervisor = binding_for(mcp_sandbox, mcp_manager.engine, actor="supervisor_001")
    async with Client(create_server("tasks", supervisor), raise_exceptions=True) as sdk:
        result = await TrustedClient(sdk, supervisor.config).write(
            "update_task", reopen, LogicalOperation.new()
        )
        assert assert_success(result)["version"] == 3


async def test_viewer_denial_and_metadata_cannot_impersonate(mcp_sandbox, mcp_manager):
    viewer = binding_for(mcp_sandbox, mcp_manager.engine, actor="viewer_001")
    before = mcp_sandbox.snapshot()
    async with Client(create_server("tasks", viewer), raise_exceptions=True) as sdk:
        arguments = {"customer_id": "customer_001", "title": "Denied"}
        proof = sign_operation(viewer.config, "create_task", arguments, LogicalOperation.new())
        proof.update(actor_id="supervisor_001", tenant_id="otherdesk", run_id="docker_probe_01")
        assert_error(await sdk.call_tool("create_task", arguments, meta=proof), "permission_denied")
        assert_error(
            await sdk.call_tool(
                "create_task", {**arguments, "actor_id": "supervisor_001"}, meta=proof
            ),
            "validation_error",
        )
    assert mcp_sandbox.snapshot() == before
    assert counts(mcp_sandbox) == (4, 0, 0)


@pytest.mark.parametrize("approval", [False, True])
async def test_scenario_policy_and_approval_cannot_be_bypassed(
    mcp_sandbox_factory, mcp_manager, approval
):
    access = baseline_access()
    if approval:
        access.approval_required = ["create_task"]
    else:
        access.permitted.remove("create_task")
    sandbox = mcp_sandbox_factory(access=access)
    bound = binding_for(sandbox, mcp_manager.engine)
    before = sandbox.snapshot()
    async with Client(create_server("tasks", bound), raise_exceptions=True) as sdk:
        result = await TrustedClient(sdk, bound.config).write(
            "create_task",
            {"customer_id": "customer_001", "title": "Denied"},
            LogicalOperation.new(),
        )
        assert_error(result, "approval_required" if approval else "permission_denied")
    assert sandbox.snapshot() == before
    assert counts(sandbox) == (4, 0, 0)


async def test_concurrent_retry_safety_over_protocol(bound, mcp_sandbox):
    async with Client(create_server("tasks", bound), raise_exceptions=True) as sdk:
        client = TrustedClient(sdk, bound.config)
        operation = LogicalOperation.new()
        results = await asyncio.gather(
            *(
                client.write(
                    "create_task",
                    {"customer_id": "customer_001", "title": "Concurrent retry"},
                    operation,
                )
                for _ in range(4)
            )
        )
        tasks = [assert_success(result) for result in results]
        assert all(item == tasks[0] for item in tasks)
    assert counts(mcp_sandbox) == (5, 1, 1)


async def test_response_discard_then_reconnect_and_retry(bound, mcp_sandbox):
    operation = LogicalOperation.new()
    arguments = {"customer_id": "customer_001", "title": "Lost response simulation"}
    async with Client(create_server("tasks", bound), raise_exceptions=True) as sdk:
        # The server commits; deliberately discard the response at the trusted client.
        await TrustedClient(sdk, bound.config).write("create_task", arguments, operation)
    async with Client(create_server("tasks", bound), raise_exceptions=True) as sdk:
        assert_success(
            await TrustedClient(sdk, bound.config).write("create_task", arguments, operation)
        )
    assert counts(mcp_sandbox) == (5, 1, 1)


async def test_independent_runs_no_cross_run_arguments_or_proofs(mcp_sandbox_factory, mcp_manager):
    first, second = mcp_sandbox_factory(), mcp_sandbox_factory()
    initial = second.snapshot()
    one, two = binding_for(first, mcp_manager.engine), binding_for(second, mcp_manager.engine)
    arguments = {"customer_id": "customer_001", "title": "First run only"}
    async with Client(create_server("tasks", one), raise_exceptions=True) as sdk:
        client = TrustedClient(sdk, one.config)
        task = assert_success(await client.write("create_task", arguments, LogicalOperation.new()))
        assert_error(
            await client.write(
                "create_task", {**arguments, "run_id": second.run_id}, LogicalOperation.new()
            ),
            "validation_error",
        )
    async with Client(create_server("tasks", two), raise_exceptions=True) as sdk:
        result = await sdk.call_tool(
            "create_task",
            arguments,
            meta=sign_operation(one.config, "create_task", arguments, LogicalOperation.new()),
        )
        assert_error(result, "permission_denied")
        assert_error(
            await TrustedClient(sdk, two.config).write(
                "update_task",
                {
                    "task_id": task["task_id"],
                    "expected_version": 1,
                    "patch": {"status": "resolved"},
                },
                LogicalOperation.new(),
            ),
            "not_found",
        )
    assert second.snapshot() == initial
    first.reset()
    assert first.snapshot() == initial


async def test_reprovision_cannot_redirect_existing_server(bound, mcp_sandbox, mcp_manager):
    server = create_server("business", bound)
    mcp_manager.cleanup(mcp_sandbox.run_id)
    mcp_manager.provision(mcp_sandbox.run_id, load_baseline(), baseline_access())
    async with Client(server, raise_exceptions=True) as sdk:
        assert_error(
            await sdk.call_tool("get_order", {"order_id": "order_001"}), "permission_denied"
        )


@pytest.mark.parametrize(
    "actor,tenant", [("missing_actor", "opsdesk"), ("viewer_001", "otherdesk")]
)
async def test_invalid_launch_actor_rejected(mcp_sandbox, mcp_manager, actor, tenant):
    with pytest.raises(ValueError, match="launch actor"):
        binding_for(mcp_sandbox, mcp_manager.engine, actor=actor, tenant=tenant)


@pytest.mark.parametrize(
    "path", sorted((ROOT / "benchmarks/development").glob("*.json")), ids=lambda path: path.stem
)
async def test_all_scenarios_can_bind_protocol_servers(path, mcp_sandbox_factory, mcp_manager):
    scenario = load_scenario(path)
    sandbox = mcp_sandbox_factory(from_scenario(scenario), scenario.tools)
    bound = binding_for(
        sandbox, mcp_manager.engine, actor=scenario.actor.actor_id, tenant=scenario.actor.tenant_id
    )
    async with Client(create_server("business", bound), raise_exceptions=True) as sdk:
        assert len((await sdk.list_tools()).tools) == 3
        result = await sdk.call_tool("get_order", {"order_id": "order_001"})
        if "get_order" in scenario.tools.permitted:
            assert assert_success(result)["status"] == "shipped"
        else:
            assert_error(result, "permission_denied")
    assert sandbox.verify()


async def test_stdio_all_domains_and_write_retry(bound, mcp_sandbox):
    names = set()
    for domain in ("documents", "business", "tasks"):
        async with connect_stdio(domain, bound.config) as client:
            listing = await client.discover()
            names.update(tool.name for tool in listing.tools)
            if domain == "tasks":
                operation = LogicalOperation.new()
                arguments = {"customer_id": "customer_001", "title": "Stdio task"}
                first = assert_success(await client.write("create_task", arguments, operation))
                assert (
                    assert_success(await client.write("create_task", arguments, operation)) == first
                )
            elif domain == "business":
                assert (
                    assert_success(await client.read("get_order", {"order_id": "order_001"}))[
                        "total_amount"
                    ]
                    == "25.00"
                )
            else:
                assert_success(await client.read("search_documents", {"query": "refund"}))
    assert len(names) == 8
    assert counts(mcp_sandbox) == (5, 1, 1)


async def test_stdio_missing_context_fails_without_disclosure():
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("OPSDESK_MCP_")
    }
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "agent_reliability_lab.mcp.cli", "serve", "tasks"],
        input="",
        capture_output=True,
        text=True,
        env=environment,
        timeout=15,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "ValidationError" in result.stderr
    assert "Traceback" not in result.stderr
    assert "postgresql+psycopg" not in result.stderr


async def test_injected_database_failure_is_structured(bound, monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy.exc import OperationalError

    @contextmanager
    def unavailable(*args, **kwargs):
        raise OperationalError("SENSITIVE_SQL", {}, RuntimeError("SENSITIVE_DSN"))
        yield

    monkeypatch.setattr(bound.sandbox, "transaction", unavailable)
    async with Client(create_server("business", bound), raise_exceptions=True) as sdk:
        result = await sdk.call_tool("get_customer", {"customer_id": "customer_001"})
        assert_error(result, "database_unavailable")
        assert result.structured_content["error"]["retryable"]
        assert "SENSITIVE" not in result.model_dump_json()


async def test_real_unavailable_database_is_structured(bound):
    import socket
    from dataclasses import replace

    from agent_reliability_lab.opsdesk.database import Sandbox
    from agent_reliability_lab.opsdesk.services import OpsDeskService

    # Reserve a non-listening loopback port; the real libpq connection must fail.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        engine = sa.create_engine(
            bound.sandbox.engine.url.set(port=reserved.getsockname()[1]),
            connect_args={"connect_timeout": 1},
            hide_parameters=True,
        )
        sandbox = Sandbox(engine, bound.config.run_id)
        unavailable = replace(bound, sandbox=sandbox, service=OpsDeskService(sandbox))
        try:
            async with Client(create_server("business", unavailable), raise_exceptions=True) as sdk:
                result = await sdk.call_tool("get_customer", {"customer_id": "customer_001"})
                assert_error(result, "database_unavailable")
                assert "Traceback" not in result.model_dump_json()
                assert "postgresql+psycopg" not in result.model_dump_json()
        finally:
            engine.dispose()
