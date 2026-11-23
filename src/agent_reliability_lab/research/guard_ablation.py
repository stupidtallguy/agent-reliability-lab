"""Preregistered order and descriptive cell counts for the local guard study."""

from itertools import product

from agent_reliability_lab.adversarial.contracts import GuardFactors
from agent_reliability_lab.opsdesk.fixtures import digest

INTERVENTION = "guard_factorial_v1"


def factorial_orders(seed):
    """One seed-ordered eight-cell block and its exact reverse."""
    pairs = sorted(product((False, True), repeat=2), key=lambda state: digest([seed, state]))
    arms = ["baseline", "guarded"]
    first = [
        (
            1,
            list(arms if index % 2 == 0 else reversed(arms)),
            {
                arm: GuardFactors(
                    system_policy=system,
                    observation_framing=frame,
                    task_scope_filter=arm == "guarded",
                ).model_dump(mode="json")
                for arm in arms
            },
        )
        for index, (system, frame) in enumerate(pairs)
    ]
    return first + [(2, order[::-1], factors) for _, order, factors in reversed(first)]


def descriptive_cells(rows):
    cells = {}
    for row in rows:
        for arm, factors in row["factors"].items():
            key = digest(factors)
            cell = cells.setdefault(
                key,
                {
                    "factors": factors,
                    "planned_trials": 0,
                    "verified_successes": 0,
                    "verified_failures": 0,
                    "unresolved": 0,
                },
            )
            cell["planned_trials"] += 1
            observation = row["arms"].get(arm, {}).get("measurements", {}).get("task_success", {})
            status = observation.get("status") if row["comparison"] == "verified" else None
            field = {
                "verified_success": "verified_successes",
                "verified_failure": "verified_failures",
            }.get(status, "unresolved")
            cell[field] += 1
    return {"method": "factorial_cell_counts_v1", "cells": list(cells.values())}
