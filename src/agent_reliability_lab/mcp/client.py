"""Trusted SDK client: explicit operation identities, signed metadata, no auto-retries."""

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp import Client, StdioServerParameters, types

from agent_reliability_lab.mcp.context import LaunchConfig, LogicalOperation, sign_operation
from agent_reliability_lab.mcp.contracts import Domain
from agent_reliability_lab.opsdesk.services import READS, WRITES


class TrustedClient:
    def __init__(self, client: Client, config: LaunchConfig) -> None:
        self._client = client
        self._config = config

    async def discover(self) -> types.ListToolsResult:
        return await self._client.list_tools(cache_mode="bypass")

    async def read(self, tool: str, arguments: dict) -> types.CallToolResult:
        if tool not in READS:
            raise ValueError("read accepts only known read tools")
        return await self._client.call_tool(tool, arguments)

    async def write(
        self, tool: str, arguments: dict, operation: LogicalOperation
    ) -> types.CallToolResult:
        if tool not in WRITES:
            raise ValueError("write accepts only known write tools")
        return await self._client.call_tool(
            tool, arguments, meta=sign_operation(self._config, tool, arguments, operation)
        )


@asynccontextmanager
async def connect_stdio(
    domain: Domain, config: LaunchConfig, *, python_executable: str = sys.executable
) -> AsyncIterator[TrustedClient]:
    parameters = StdioServerParameters(
        command=python_executable,
        args=["-m", "agent_reliability_lab.mcp.cli", "serve", domain],
        env=config.child_env(),
    )
    async with Client(parameters, cache=None, read_timeout_seconds=25) as client:
        yield TrustedClient(client, config)
