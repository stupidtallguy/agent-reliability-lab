"""Deterministic plans, not an NLP model or benchmark scoring engine."""

import json

CASES = ("order", "policy", "customer", "multi_step", "create", "viewer_denied", "error")


def call(name: str, **arguments) -> dict:
    return {"calls": [{"name": name, "arguments_json": json.dumps(arguments)}]}


def demo_plan(case: str) -> tuple[str, str, list[dict]]:
    actor = "support_001"
    plans = {
        "order": ("Retrieve order_001 status.", [call("get_order", order_id="order_001")]),
        "policy": (
            "Find the refund policy and read it.",
            [
                call("search_documents", query="refund"),
                call("get_document", document_id="refund_policy"),
            ],
        ),
        "customer": (
            "Retrieve customer_001 and their orders.",
            [
                call("get_customer", customer_id="customer_001"),
                call("list_customer_orders", customer_id="customer_001"),
            ],
        ),
        "multi_step": (
            "Read order_001 and task policy, inspect tasks, then start task_001.",
            [
                call("get_order", order_id="order_001"),
                call("get_document", document_id="task_policy"),
                call("list_tasks", limit=5),
                call(
                    "update_task",
                    task_id="task_001",
                    expected_version=1,
                    patch={"status": "in_progress"},
                ),
            ],
        ),
        "create": (
            "Create a follow-up support task for customer_001.",
            [call("create_task", customer_id="customer_001", title="Agent demo follow-up")],
        ),
        "viewer_denied": (
            "Attempt to start task_001 as a viewer.",
            [
                call(
                    "update_task",
                    task_id="task_001",
                    expected_version=1,
                    patch={"status": "in_progress"},
                )
            ],
        ),
        "error": (
            "Retrieve an order that does not exist.",
            [call("get_order", order_id="order_missing")],
        ),
    }
    task, script = plans[case]
    if case == "viewer_denied":
        actor = "viewer_001"
    script.append(
        {
            "answer": "Scripted demonstration ended; inspect tool observations in the journal.",
            "declared_complete": case not in {"viewer_denied", "error"},
        }
    )
    return task, actor, script
