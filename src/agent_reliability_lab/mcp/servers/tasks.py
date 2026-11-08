"""Task adapters delegate all write rules to existing services."""

from mcp.server import Server

from agent_reliability_lab.mcp.context import BoundContext
from agent_reliability_lab.mcp.contracts import CreateTaskInput, UpdateTaskInput
from agent_reliability_lab.mcp.servers.shared import ToolSpec, build_server
from agent_reliability_lab.opsdesk.contracts import Page, TaskList, TaskView


def create_server(binding: BoundContext) -> Server:
    return build_server(
        "tasks",
        binding,
        (
            ToolSpec(
                "list_tasks",
                "List tenant-scoped tasks with customer/status filters and bounded ID pagination.",
                TaskList,
                Page[TaskView],
            ),
            ToolSpec(
                "create_task",
                "Create a permitted support task with trusted host retry metadata.",
                CreateTaskInput,
                TaskView,
            ),
            ToolSpec(
                "update_task",
                "Update permitted task fields at an observed version with host retry metadata.",
                UpdateTaskInput,
                TaskView,
            ),
        ),
    )
