"""Read-only business domain adapters."""

from mcp.server import Server

from agent_reliability_lab.mcp.context import BoundContext
from agent_reliability_lab.mcp.contracts import CustomerLookup, OrderLookup
from agent_reliability_lab.mcp.servers.shared import ToolSpec, build_server
from agent_reliability_lab.opsdesk.contracts import CustomerOrders, CustomerView, OrderView, Page


def create_server(binding: BoundContext) -> Server:
    return build_server(
        "business",
        binding,
        (
            ToolSpec(
                "get_order",
                "Read a synthetic order visible to the bound actor's tenant.",
                OrderLookup,
                OrderView,
                "order_id",
            ),
            ToolSpec(
                "get_customer",
                "Read a synthetic customer visible to the bound actor's tenant.",
                CustomerLookup,
                CustomerView,
                "customer_id",
            ),
            ToolSpec(
                "list_customer_orders",
                "List a customer's tenant-scoped orders in ID order with bounded pagination.",
                CustomerOrders,
                Page[OrderView],
            ),
        ),
    )
