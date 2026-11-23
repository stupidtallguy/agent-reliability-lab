"""Recover plans only from frozen host evidence or a hash-verified manifest.

Runtime plans intentionally omit attacker objectives. They can establish counts,
but cannot reconstruct an objective oracle. Never inspect model prose for plans.
"""

import json

from agent_reliability_lab.adversarial.contracts import Defense, HarnessSpec, RuntimePlan
from agent_reliability_lab.evaluation.contracts import ExperimentConfig
from agent_reliability_lab.opsdesk.fixtures import digest


class ExperimentalContextError(ValueError):
    code = "experimental_context_missing"

    def __init__(self, plan, code=None):
        self.plan = plan
        self.code = code or self.code
        super().__init__(self.code)


def unavailable_plan():
    return dict(
        schema_version="1.0",
        status="unavailable",
        configured_trial=None,
        attack_count=None,
        fault_count=None,
        benign_control=None,
        source=None,
        source_hash=None,
    )


def plan_for(harness, source, source_hash, configured=True):
    return dict(
        schema_version="1.0",
        status="known",
        configured_trial=configured,
        attack_count=len(harness.attacks) if harness else 0,
        fault_count=len(harness.faults) if harness else 0,
        benign_control=harness.benign_control if harness else False,
        source=source,
        source_hash=source_hash,
    )


def manifest_plan(experiment, meta):
    if experiment is None:
        return None
    try:
        manifest = experiment["manifest"]
        if (
            experiment["experiment_id"] != meta["experiment_id"]
            or digest(manifest) != experiment["manifest_hash"]
        ):
            raise ValueError()
        cases = [c for c in manifest["cases"] if c["scenario_id"] == meta["scenario_id"]]
        if len(cases) != 1 or cases[0]["scenario_hash"] != meta["scenario_hash"]:
            raise ValueError()
        config = ExperimentConfig.model_validate_json(json.dumps(manifest["config"]))
        harness = config.harnesses.get(meta["scenario_id"])
        if harness and harness.scenario_hash != meta["scenario_hash"]:
            raise ValueError()
        return (
            config,
            harness,
            plan_for(harness, "frozen_manifest", experiment["manifest_hash"], bool(harness)),
        )
    except (ValueError, TypeError, KeyError):
        raise ExperimentalContextError(
            unavailable_plan(), "experimental_manifest_conflict"
        ) from None


def runtime_plan(evidence):
    try:
        config = evidence.execution.get("config", {}) if evidence else {}
        if not isinstance(config, dict):
            return unavailable_plan()
        value = config.get("runtime_plan")
        if value is None:
            return unavailable_plan()
        runtime = RuntimePlan.model_validate_json(json.dumps(value))
        return dict(
            schema_version="1.0",
            status="known",
            configured_trial=True,
            attack_count=len(runtime.attacks),
            fault_count=len(runtime.faults),
            benign_control=None,
            source="frozen_execution_runtime_plan",
            source_hash=digest(value),
        )
    except (ValueError, TypeError):
        return unavailable_plan()


def resolve_context(evidence, meta, experiment=None):
    """Return an ephemeral copy and plan; never repair the persisted capture."""
    trusted = manifest_plan(experiment, meta)
    plan = trusted[2] if trusted else runtime_plan(evidence)
    if evidence is None:
        raise ExperimentalContextError(plan)
    context = evidence.experimental
    execution_config = evidence.execution.get("config", {})
    if not isinstance(execution_config, dict):
        raise ExperimentalContextError(plan, "experimental_context_conflict")
    if context is None and trusted:
        config, harness, plan = trusted
        if harness is None:
            if execution_config.get("runtime_plan") is not None:
                raise ExperimentalContextError(plan, "experimental_context_conflict")
            return evidence, plan
        defense = Defense(
            configuration=config.defense,
            factors=config.guard_factors,
            write_scopes=config.write_scopes.get(meta["scenario_id"], []),
        )
        if digest(execution_config.get("runtime_plan")) != digest(
            harness.runtime().model_dump(mode="json")
        ) or execution_config.get("defense") != defense.model_dump(mode="json"):
            raise ExperimentalContextError(plan, "experimental_context_conflict")
        used = evidence.model_copy(deep=True)
        used.experimental = dict(
            version="1.0",
            harness=harness.model_dump(mode="json"),
            harness_hash=digest(harness.model_dump(mode="json")),
            runtime_hash=digest(harness.runtime().model_dump(mode="json")),
            defense=defense.model_dump(mode="json"),
            pairing_id=config.pairing_id,
            pair_key=f"{meta['scenario_id']}:{meta['trial_index']}",
        )
        # model_visibility_capture is not invented when the original flag is lost.
        return used, {**plan, "context_recovered": True}
    if context is None:
        raise ExperimentalContextError(plan)
    try:
        harness = HarnessSpec.model_validate_json(json.dumps(context["harness"]))
        fingerprint = digest(harness.model_dump(mode="json"))
        runtime_hash = digest(harness.runtime().model_dump(mode="json"))
        if (
            harness.scenario_hash != meta["scenario_hash"]
            or context["harness_hash"] != fingerprint
            or context["runtime_hash"] != runtime_hash
            or digest(execution_config.get("runtime_plan")) != runtime_hash
            or context["defense"] != execution_config.get("defense")
        ):
            raise ValueError()
        if trusted:
            config, expected, plan = trusted
            defense = Defense(
                configuration=config.defense,
                factors=config.guard_factors,
                write_scopes=config.write_scopes.get(meta["scenario_id"], []),
            )
            if (
                expected is None
                or digest(expected.model_dump(mode="json")) != fingerprint
                or context["defense"] != defense.model_dump(mode="json")
            ):
                raise ValueError()
        else:
            plan = plan_for(harness, "frozen_capture", fingerprint)
        return evidence, plan
    except (ValueError, TypeError, KeyError):
        raise ExperimentalContextError(plan, "experimental_context_conflict") from None


def attach_plan(result, plan, context_error=None):
    experimental = result.experimental
    experimental.setdefault("schema_version", "1.4")
    experimental["planned_trial"] = plan
    if context_error:
        experimental["context_error"] = context_error
    attacks = plan.get("attack_count")
    invalid = {
        g["injection_id"]
        for g in experimental.get("objectives", [])
        if g.get("exposure_evidence_valid") is False
    }
    records = [
        None if e.get("injection_id") in invalid else e.get("exposed")
        for e in experimental.get("exposures", [])
        if e.get("kind") == "attack"
    ]
    experimental["verified_attack_exposure"] = (
        ((True if True in records else None if None in records else False) if records else None)
        if attacks
        else (False if attacks == 0 else None)
    )
    return result
