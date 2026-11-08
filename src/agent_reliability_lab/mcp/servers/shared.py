"""SDK v2 callbacks with explicit Pydantic input/output validation."""

import logging
from dataclasses import dataclass
from functools import partial

import anyio
from mcp import MCPError, types
from mcp.server import Server, ServerRequestContext
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import OperationalError

from agent_reliability_lab import __version__
from agent_reliability_lab.mcp.context import BoundContext, canonical, service_key
from agent_reliability_lab.mcp.contracts import Domain, Envelope, Provenance
from agent_reliability_lab.mcp.errors import safe_error, service_error
from agent_reliability_lab.opsdesk.contracts import Lookup, ServiceError, TaskCreate, TaskUpdate
from agent_reliability_lab.opsdesk.services import WRITES

logger = logging.getLogger(__name__)
MAX_ARGUMENT_BYTES = 16 * 1024
MAX_RESULT_BYTES = 64 * 1024  # Structured payload; duplicated text/framing is additional.


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    lookup_field: str | None = None

    @property
    def envelope_model(self) -> type[BaseModel]:
        return Envelope[self.output_model]

    def discovery(self) -> types.Tool:
        write = self.name in WRITES
        return types.Tool(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
            output_schema=self.envelope_model.model_json_schema(mode="serialization"),
            annotations=types.ToolAnnotations(
                read_only_hint=not write,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )


def build_server(domain: Domain, binding: BoundContext, specs: tuple[ToolSpec, ...]) -> Server:
    tools = {spec.name: spec for spec in specs}
    limiter = anyio.CapacityLimiter(4)

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        if params is not None and params.cursor is not None:
            raise MCPError(code=-32602, message="Tool discovery cursor is not supported.")
        return types.ListToolsResult(tools=[spec.discovery() for spec in specs])

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        spec = tools.get(params.name)
        if spec is None:
            raise MCPError(
                code=-32602,
                message="Unknown tool.",
                data={"code": "unknown_tool", "retryable": False},
            )
        provenance = Provenance(
            domain=domain,
            tool=spec.name,
            fixture_id=binding.fixture_id,
            fixture_version=binding.fixture_version,
            seed_hash=binding.seed_hash,
        )

        def result(data=None, error=None) -> types.CallToolResult:
            envelope = spec.envelope_model(data=data, error=error, provenance=provenance)
            payload = envelope.model_dump(mode="json")
            encoded = canonical(payload)
            if len(encoded) > MAX_RESULT_BYTES:
                return result(error=safe_error("response_too_large"))
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=encoded.decode())],
                structured_content=payload,
                is_error=error is not None,
            )

        arguments = params.arguments or {}
        try:
            if len(canonical(arguments)) > MAX_ARGUMENT_BYTES:
                return result(error=safe_error("validation_error"))
            request = spec.input_model.model_validate(arguments)
        except (ValidationError, ValueError, TypeError):
            return result(error=safe_error("validation_error"))
        try:
            if spec.lookup_field:
                request = Lookup(record_id=getattr(request, spec.lookup_field))
            elif spec.name in WRITES:
                key = service_key(binding.config, spec.name, arguments, params.meta)
                model = TaskCreate if spec.name == "create_task" else TaskUpdate
                request = model.model_validate(
                    {**request.model_dump(exclude_unset=True), "idempotency_key": key}
                )
            response = await anyio.to_thread.run_sync(
                partial(binding.invoke, spec.name, request), limiter=limiter
            )
            # Normalize generic service pages and verify serialized output before returning it.
            data = spec.output_model.model_validate_json(response.model_dump_json())
            return result(data=data)
        except ServiceError as error:
            safe = service_error(error)
            if safe.code == "internal_error":
                logger.exception(
                    "Unrecognized service failure correlation_id=%s", safe.correlation_id
                )
            return result(error=safe)
        except OperationalError:
            error = safe_error("database_unavailable", retryable=True)
            logger.exception("Database failure correlation_id=%s", error.correlation_id)
            return result(error=error)
        except Exception:
            error = safe_error("internal_error")
            logger.exception("Tool failure correlation_id=%s", error.correlation_id)
            return result(error=error)

    return Server(
        f"opsdesk-{domain}",
        version=__version__,
        description=f"Synthetic OpsDesk {domain} tools bound to trusted host context.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        get_tool_input_schema=lambda name: (
            tools[name].input_model.model_json_schema() if name in tools else None
        ),
    )
