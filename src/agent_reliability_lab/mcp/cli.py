"""Trusted stdio launch and an isolated, LLM-free developer demonstration."""

import argparse
import json
import logging
import secrets
import sys
import uuid
from contextlib import AsyncExitStack

import anyio
from mcp import types
from mcp.server.stdio import stdio_server
from pydantic import SecretStr

from agent_reliability_lab.mcp.client import connect_stdio
from agent_reliability_lab.mcp.context import BoundContext, LaunchConfig, LogicalOperation
from agent_reliability_lab.mcp.servers import create_server
from agent_reliability_lab.opsdesk.database import SandboxManager, engine_from_env, schema_for
from agent_reliability_lab.opsdesk.fixtures import baseline_access, load_baseline
from agent_reliability_lab.opsdesk.services import WRITES


def display(label: str, result: types.CallToolResult) -> None:
    print(
        json.dumps(
            {"step": label, "is_error": result.is_error, "result": result.structured_content},
            indent=2,
        )
    )


def tool_summary(domain: str, listing: types.ListToolsResult, *, full: bool = False) -> None:
    tools = []
    for tool in listing.tools:
        tools.append(
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema
                if full
                else {
                    "fields": list(tool.input_schema.get("properties", {})),
                    "required": tool.input_schema.get("required", []),
                },
                "output_schema": tool.output_schema
                if full
                else {"fields": list((tool.output_schema or {}).get("properties", {}))},
            }
        )
    print(json.dumps({"server": domain, "tools": tools}, indent=2))


async def serve(domain: str) -> None:
    config = LaunchConfig.from_env()
    engine = engine_from_env()
    try:
        binding = BoundContext.bind(engine, config)
        server = create_server(domain, binding)
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        engine.dispose()


async def demonstrate(run_id: str) -> None:
    schema_for(run_id)
    if not run_id.startswith("mcp_demo_"):
        raise ValueError("demonstration run IDs must start with mcp_demo_")
    engine = engine_from_env()
    manager = SandboxManager(engine)
    created = False
    try:
        # Occupied names fail before created=True; never remove a preexisting run.
        sandbox = manager.provision(run_id, load_baseline(), baseline_access())
        created = True
        config = LaunchConfig(
            run_id=run_id,
            actor_id="support_001",
            tenant_id="opsdesk",
            signing_key=SecretStr(secrets.token_hex(32)),
        )
        async with AsyncExitStack() as stack:
            clients = {
                domain: await stack.enter_async_context(connect_stdio(domain, config))
                for domain in ("documents", "business", "tasks")
            }
            for domain, client in clients.items():
                tool_summary(domain, await client.discover())
            order = await clients["business"].read("get_order", {"order_id": "order_001"})
            display("read_order", order)
            if order.is_error:
                raise RuntimeError("demo read failed")
            operation = LogicalOperation.new()
            arguments = {"customer_id": "customer_001", "title": "MCP demonstration follow-up"}
            first = await clients["tasks"].write("create_task", arguments, operation)
            retry = await clients["tasks"].write("create_task", arguments, operation)
            display("permitted_create", first)
            display("identical_retry", retry)
            if (
                first.is_error
                or retry.structured_content["data"] != first.structured_content["data"]
            ):
                raise RuntimeError("demo write/retry failed")
            task = first.structured_content["data"]
            updated = await clients["tasks"].write(
                "update_task",
                {
                    "task_id": task["task_id"],
                    "expected_version": task["version"],
                    "patch": {"status": "resolved"},
                },
                LogicalOperation.new(),
            )
            display("permitted_update", updated)
            if updated.is_error:
                raise RuntimeError("demo update failed")
            viewer = LaunchConfig(
                run_id=run_id,
                actor_id="viewer_001",
                tenant_id="opsdesk",
                signing_key=config.signing_key,
            )
            viewer_client = await stack.enter_async_context(connect_stdio("tasks", viewer))
            denied = await viewer_client.write("create_task", arguments, LogicalOperation.new())
            display("viewer_denied", denied)
            if (
                not denied.is_error
                or denied.structured_content["error"]["code"] != "permission_denied"
            ):
                raise RuntimeError("demo denial check failed")
        sandbox.reset()
        if not sandbox.verify():
            raise RuntimeError("demo reset failed")
        print(json.dumps({"step": "reset_verified", "run": run_id}))
    finally:
        try:
            if created:
                manager.cleanup(run_id)
                print(json.dumps({"step": "cleaned_up", "run": run_id}))
        finally:
            engine.dispose()


async def client_command(args: argparse.Namespace) -> int:
    config = LaunchConfig.from_env()
    async with connect_stdio(args.domain, config) as client:
        if args.command == "list":
            tool_summary(args.domain, await client.discover(), full=args.full_schema)
            return 0
        arguments = json.loads(args.arguments)
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a JSON object")
        if args.tool in WRITES:
            if args.operation_id is None:
                raise ValueError(
                    "writes require a host-chosen --operation-id; reuse it for retries"
                )
            result = await client.write(
                args.tool, arguments, LogicalOperation(operation_id=args.operation_id)
            )
        else:
            result = await client.read(args.tool, arguments)
        display(args.tool, result)
        return int(result.is_error)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bound OpsDesk stdio MCP servers and trusted client"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "list", "call"):
        command = commands.add_parser(name)
        command.add_argument("domain", choices=["documents", "business", "tasks"])
        if name == "list":
            command.add_argument("--full-schema", action="store_true")
        if name == "call":
            command.add_argument("tool")
            command.add_argument("--arguments", required=True)
            command.add_argument("--operation-id")
    demo = commands.add_parser("demo")
    demo.add_argument("--run", default="mcp_demo_" + uuid.uuid4().hex[:12])
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    try:
        if args.command == "serve":
            anyio.run(serve, args.domain)
            return 0
        if args.command == "demo":
            anyio.run(demonstrate, args.run)
            return 0
        return anyio.run(client_command, args)
    except Exception as error:
        # Startup errors can include DSNs or input values. Only trusted developers may
        # opt into exception logging; the default never prints the original exception.
        print(
            f"MCP command failed ({type(error).__name__}); "
            "check trusted configuration and service health.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
