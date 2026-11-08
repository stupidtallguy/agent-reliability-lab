"""Discover contracts and execute through existing trusted MCP clients only."""

import copy
from contextlib import AsyncExitStack

import jsonschema
from mcp import Client
from sqlalchemy.engine import Engine

from agent_reliability_lab.agent.config import AgentConfig
from agent_reliability_lab.mcp.client import TrustedClient, connect_stdio
from agent_reliability_lab.mcp.context import BoundContext, LaunchConfig, LogicalOperation
from agent_reliability_lab.mcp.servers import create_server

WRITES = frozenset({"create_task", "update_task"})


def provider_tools(catalog: list[dict]) -> list[dict]:
    # Explicit non-strict mode preserves MCP optional/default semantics. Local
    # JSON Schema + MCP Pydantic validation remain authoritative.
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": copy.deepcopy(tool["input_schema"]),
                "strict": False,
            },
        }
        for tool in catalog
    ]


class ToolSession:
    def __init__(self, engine: Engine, launch: LaunchConfig, config: AgentConfig) -> None:
        self.engine, self.launch, self.config = engine, launch, config
        self.stack = AsyncExitStack()
        self.clients: dict[str, TrustedClient] = {}
        self.catalog: list[dict] = []

    async def __aenter__(self) -> "ToolSession":
        try:
            for domain in self.config.domains:
                if self.config.transport == "stdio":
                    client = await self.stack.enter_async_context(
                        connect_stdio(domain, self.launch)
                    )
                else:
                    binding = BoundContext.bind(self.engine, self.launch)
                    sdk = await self.stack.enter_async_context(
                        Client(create_server(domain, binding), raise_exceptions=True, cache=None)
                    )
                    client = TrustedClient(sdk, self.launch)
                self.clients[domain] = client
                for tool in (await client.discover()).tools:
                    self.catalog.append(
                        {
                            "name": tool.name,
                            "domain": domain,
                            "description": tool.description or "",
                            "input_schema": tool.input_schema,
                            "output_schema": tool.output_schema,
                        }
                    )
            if len({tool["name"] for tool in self.catalog}) != len(self.catalog):
                raise ValueError("duplicate discovered tool names")
            return self
        except BaseException:
            await self.stack.aclose()
            raise

    async def __aexit__(self, *args) -> None:
        await self.stack.aclose()

    async def call(self, tool: dict, arguments: dict, operation_id: str | None) -> dict:
        client = self.clients[tool["domain"]]
        if tool["name"] in WRITES:
            result = await client.write(
                tool["name"], arguments, LogicalOperation(operation_id=operation_id)
            )
        else:
            result = await client.read(tool["name"], arguments)
        payload = result.structured_content
        jsonschema.Draft202012Validator(tool["output_schema"]).validate(payload)
        if result.is_error != (payload.get("error") is not None):
            raise ValueError("inconsistent MCP error envelope")
        return payload
