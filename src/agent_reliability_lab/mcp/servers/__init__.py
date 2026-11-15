"""Three domain-specific server factories."""

from mcp.server import Server

from agent_reliability_lab.mcp.context import BoundContext
from agent_reliability_lab.mcp.contracts import Domain
from agent_reliability_lab.mcp.servers import business, documents, tasks
from agent_reliability_lab.mcp.servers.shared import ToolSpec, build_server
from agent_reliability_lab.reliability.notifications import TOOL, LocalReceipt, NotificationInput


def create_server(domain: Domain, binding: BoundContext) -> Server:
    if domain == "notifications":
        return build_server(
            domain,
            binding,
            (
                ToolSpec(
                    TOOL,
                    "Record a synthetic notification intent and its outbox entry.",
                    NotificationInput,
                    LocalReceipt,
                ),
            ),
        )
    return {
        "documents": documents.create_server,
        "business": business.create_server,
        "tasks": tasks.create_server,
    }[domain](binding)
