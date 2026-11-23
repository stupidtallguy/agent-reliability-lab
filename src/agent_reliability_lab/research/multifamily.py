"""Frozen development corpus and descriptive analysis for the local CP24 pilot."""

from collections import Counter

from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.platform.demo import assets
from agent_reliability_lab.research.benchmark_contracts import BenchmarkDataset

INTERVENTION = "guard_multifamily_v1"
CASE_LIMITS = {
    "cp24_shipment_followup": 1,
    "cp24_intake_review": 2,
    "cp24_collection_policy": 0,
    "cp24_return_receipt": 1,
}


def reviewed_dataset() -> BenchmarkDataset:
    dataset = BenchmarkDataset.model_validate_json(
        (assets() / "benchmarks/research/cp24-development.json").read_bytes()
    )
    if (
        [case.scenario_id for case in dataset.cases] != list(CASE_LIMITS)
        or any(case.partition != "development" for case in dataset.cases)
        or len({case.template_family for case in dataset.cases}) != len(CASE_LIMITS)
    ):
        raise ValueError("CP24 requires its four distinct reviewed development families")
    return dataset


def balanced_slots(slots, seed):
    first = sorted(
        (slot for slot in slots if slot["repetition"] == 1),
        key=lambda slot: digest([seed, slot["scenario_id"]]),
    )
    second = {slot["scenario_id"]: slot for slot in slots if slot["repetition"] == 2}
    for index, slot in enumerate(first):
        slot["order"] = ["guarded", "baseline"] if index % 2 else ["baseline", "guarded"]
        second[slot["scenario_id"]]["order"] = slot["order"][::-1]
    ordered = first + [second[slot["scenario_id"]] for slot in reversed(first)]
    for number, slot in enumerate(ordered, 1):
        slot["slot"] = f"slot_{number:04d}"
    return ordered


def descriptive_families(rows):
    families = {}
    for row in rows:
        family = families.setdefault(row["template_family"], [])
        statuses = {
            arm: record["measurements"]["task_success"]["status"]
            for arm, record in row["arms"].items()
        }
        family.append(
            {"slot": row["slot"], "comparison": row["comparison"], "arm_statuses": statuses}
        )
    verdicts = Counter(p["comparison"] for pairs in families.values() for p in pairs)
    return {
        "method": "development_family_pairs_v1",
        "families": families,
        "pair_verification": dict(verdicts),
    }
