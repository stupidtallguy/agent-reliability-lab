"""Independent, fixed scripted plans for infrastructure validation only.

These functions never inspect expected outcomes or evaluation annotations.
"""

from agent_reliability_lab.agent.demo import call


def development_script(scenario_id: str) -> list[dict] | None:
    scripts = {
        "normal_order_status": [
            call("get_order", order_id="order_001"),
            {"answer": "Order order_001 has shipped.", "declared_complete": True},
        ],
        "multi_step_resolve_task": [
            call("get_order", order_id="order_001"),
            call("get_document", document_id="policy_001"),
            call(
                "update_task", task_id="task_001", expected_version=1, patch={"status": "resolved"}
            ),
            {
                "answer": "The shipped order was checked and task_001 resolved.",
                "declared_complete": True,
            },
        ],
        "authorization_viewer_update": [
            call(
                "update_task", task_id="task_001", expected_version=1, patch={"status": "resolved"}
            ),
            {"answer": "I do not have permission to update this task.", "declared_complete": False},
        ],
        "ambiguous_refund_request": [
            {
                "answer": "Please provide a customer ID; I cannot issue refunds.",
                "declared_complete": False,
            }
        ],
    }
    return scripts.get(scenario_id)
