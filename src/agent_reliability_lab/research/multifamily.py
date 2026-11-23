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


EXPANDED_CASE_LIMITS = {
    "cp25_cancelled_order": 1,
    "cp25_warranty_triage": 1,
    "cp25_label_then_close": 2,
    "cp25_prerequisite_close": 2,
    "cp25_archive_policy": 0,
    "cp25_status_inspection": 0,
    "cp25_pickup_retry": 1,
    "cp25_requery_inventory": 1,
    "cp25_archive_policy_benign": 0,
    "cp25_status_inspection_benign": 0,
}


def reviewed_dataset(*, expanded=False) -> BenchmarkDataset:
    filename = "cp25-development.json" if expanded else "cp24-development.json"
    limits = EXPANDED_CASE_LIMITS if expanded else CASE_LIMITS
    dataset = BenchmarkDataset.model_validate_json(
        (assets() / "benchmarks/research" / filename).read_bytes()
    )
    primary = [case for case in dataset.cases if not case.harness.benign_control]
    if (
        [case.scenario_id for case in dataset.cases] != list(limits)
        or any(case.partition != "development" for case in dataset.cases)
        or len({case.template_family for case in primary}) != (8 if expanded else 4)
    ):
        raise ValueError("local paired study requires its distinct reviewed development templates")
    if expanded:
        for control in dataset.cases[len(primary) :]:
            source = next(
                case for case in primary if case.scenario_id + "_benign" == control.scenario_id
            )
            a, b = source.case.scenario, control.case.scenario
            differences = {"scenario_id", "category", "injections", "attacker_objective"}
            if (
                not source.harness.attacks
                or not control.harness.benign_control
                or control.harness.attacks
                or control.harness.faults
                or a.model_dump(exclude=differences) != b.model_dump(exclude=differences)
                or source.case.oracle.model_dump(exclude={"scenario_hash"})
                != control.case.oracle.model_dump(exclude={"scenario_hash"})
                or source.template_family != control.template_family
                or source.template_id != control.template_id
                or source.family != control.family
                or source.write_scopes != control.write_scopes
                or source.refusal != control.refusal
            ):
                raise ValueError("matched benign control differs outside its injection condition")
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


def descriptive_families(rows, *, stratified=False):
    families = {}
    for row in rows:
        family = families.setdefault(row["template_family"], [])
        statuses = {
            arm: record["measurements"]["task_success"]["status"]
            for arm, record in row["arms"].items()
        }
        pair = {"slot": row["slot"], "comparison": row["comparison"], "arm_statuses": statuses}
        if stratified:
            pair["scenario_id"] = row["scenario_id"]
            pair["condition"] = (
                "benign"
                if row["scenario_id"].endswith("_benign")
                else "injected"
                if row["family"] == "policy_resilience"
                else "primary"
            )
        family.append(pair)
    verdicts = Counter(p["comparison"] for pairs in families.values() for p in pairs)
    return {
        "method": (
            "development_family_conditions_v1" if stratified else "development_family_pairs_v1"
        ),
        "families": families,
        "pair_verification": dict(verdicts),
    }
