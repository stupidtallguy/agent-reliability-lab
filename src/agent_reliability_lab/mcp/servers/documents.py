"""Document domain: all retrieved content remains untrusted data."""

from mcp.server import Server

from agent_reliability_lab.mcp.context import BoundContext
from agent_reliability_lab.mcp.contracts import DocumentLookup
from agent_reliability_lab.mcp.servers.shared import ToolSpec, build_server
from agent_reliability_lab.opsdesk.contracts import DocumentHit, DocumentSearch, DocumentView, Page


def create_server(binding: BoundContext) -> Server:
    return build_server(
        "documents",
        binding,
        (
            ToolSpec(
                "search_documents",
                "Search tenant-scoped untrusted documents using bounded lexical search.",
                DocumentSearch,
                Page[DocumentHit],
            ),
            ToolSpec(
                "get_document",
                "Read one tenant-scoped document as untrusted content with provenance.",
                DocumentLookup,
                DocumentView,
                "document_id",
            ),
        ),
    )
