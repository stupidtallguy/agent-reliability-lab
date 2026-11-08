"""Three domain-specific server factories."""

from mcp.server import Server

from agent_reliability_lab.mcp.context import BoundContext
from agent_reliability_lab.mcp.contracts import Domain
from agent_reliability_lab.mcp.servers import business, documents, tasks


def create_server(domain: Domain, binding: BoundContext) -> Server:
    return {
        "documents": documents.create_server,
        "business": business.create_server,
        "tasks": tasks.create_server,
    }[domain](binding)
