"""Explicit pairing from frozen inputs, never inferred from trial names."""

from agent_reliability_lab.adversarial.contracts import GuardFactors
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark_contracts import (
    MULTIBLOCK_INTERVENTION,
    MULTIFAMILY_INTERVENTION,
    QUALIFICATION_INTERVENTION,
)


def verify_pair(store, baseline_id, guarded_id, oracle_reference):
    if guarded_id is None:
        return "incomplete", {}, "guarded_trial_missing"
    if baseline_id == guarded_id:
        return "excluded", {}, "same_trial"
    left, right = store.trial(baseline_id), store.trial(guarded_id)
    experiments = [store.experiment(t["experiment_id"]) for t in (left, right)]
    configs = [e["manifest"]["config"] for e in experiments]
    criteria = {}
    if not configs[0].get("pairing_id") or configs[0].get("pairing_id") != configs[1].get(
        "pairing_id"
    ):
        return "excluded", criteria, "explicit_shared_pairing_id_required"
    if [c.get("defense") for c in configs] != ["baseline", "guarded"]:
        return "excluded", criteria, "baseline_guarded_configuration_required"
    for name in ("scenario_id", "scenario_version", "scenario_hash", "trial_index", "mode"):
        criteria[name] = left.get(name, left["metadata"].get(name)) == right.get(
            name, right["metadata"].get(name)
        )
    varying = {"defense"}
    if all(item.get("configuration_id") == "guard_factorial_v1" for item in configs):
        off, on = (item.get("guard_factors") for item in configs)
        criteria["task_scope_contrast"] = (
            isinstance(off, dict)
            and off.get("version") == "guard_factorial_v1"
            and off.get("task_scope_filter") is False
            and on == off | {"task_scope_filter": True}
        )
        varying.add("guard_factors")
    left_configuration = configs[0].get("configuration_id")
    if left_configuration in {
        MULTIFAMILY_INTERVENTION,
        QUALIFICATION_INTERVENTION,
        MULTIBLOCK_INTERVENTION,
    } and left_configuration == configs[1].get("configuration_id"):
        expected = [
            GuardFactors(
                system_policy=enabled, observation_framing=enabled, task_scope_filter=enabled
            ).model_dump(mode="json")
            for enabled in (False, True)
        ]
        criteria["combined_guard_contrast"] = [
            item.get("guard_factors") for item in configs
        ] == expected
        varying.add("guard_factors")
    criteria["configuration"] = {k: v for k, v in configs[0].items() if k not in varying} == {
        k: v for k, v in configs[1].items() if k not in varying
    }
    # Environment, exact model, parameters and source hashes are frozen in the manifests.
    criteria["environment"] = (
        experiments[0]["manifest"]["provenance"] == experiments[1]["manifest"]["provenance"]
    )
    evidence = [t.get("evidence") for t in (left, right)]
    if any(e is None for e in evidence):
        return "incomplete", criteria, "frozen_evidence_missing"
    for name in ("initial_hash", "fixture_hash", "seed_hash", "initial_full"):
        criteria[name] = evidence[0][name] == evidence[1][name]
    criteria["oracle_rules"] = digest(left["oracle"]) == digest(right["oracle"])
    criteria["oracle_reference"] = oracle_reference.model_dump(mode="json")
    criteria["pairing_id"] = configs[0]["pairing_id"]
    mismatches = [key for key, value in criteria.items() if value is False]
    if mismatches:
        return "excluded", criteria, "pairing_mismatch:" + ",".join(mismatches)
    return "verified", criteria, None
