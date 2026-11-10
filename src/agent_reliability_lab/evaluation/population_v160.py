"""1.6 defensive census, using the canonical attack resolution policy."""

import json
from collections import Counter

from agent_reliability_lab.evaluation.attack_outcomes import attack_metric, resolve_trial
from agent_reliability_lab.evaluation.contracts import ExperimentConfig
from agent_reliability_lab.evaluation.execution_facts import execution_facts
from agent_reliability_lab.evaluation.metrics import proportion
from agent_reliability_lab.opsdesk.fixtures import digest


def population(experiment, trials, results, revisions=None):
    revisions = revisions or {}
    scores = {r.trial_id: r for r in results}
    materialized = {(t["scenario_id"], t["trial_index"]): t for t in trials}
    if len(materialized) != len(trials):
        raise ValueError("duplicate materialized trial slot")
    unavailable = dict(
        schema_version="1.6",
        plan_status="unavailable",
        slots=[],
        planned_trials=None,
        materialized_trials=len(trials),
        selected_scores=len(results),
        metadata_unavailable_trials=len(
            {t["trial_id"] for t in trials} | {r.trial_id for r in results}
        )
        or None,
    )
    if experiment is None:
        return unavailable
    manifest = experiment["manifest"]
    if digest(manifest) != experiment["manifest_hash"]:
        raise ValueError("manifest integrity mismatch")
    config = ExperimentConfig.model_validate_json(json.dumps(manifest["config"]))
    slots = []
    seen = set()
    for case in manifest["cases"]:
        sid = case["scenario_id"]
        harness = config.harnesses.get(sid)
        if harness and harness.scenario_hash != case["scenario_hash"]:
            raise ValueError("planned harness/scenario hash conflict")
        for index in range(1, config.repeats + 1):
            key = (sid, index)
            if key in seen:
                raise ValueError("duplicate planned slot")
            seen.add(key)
            trial = materialized.get(key)
            r = scores.get(trial["trial_id"]) if trial else None
            slot = dict(
                scenario_id=sid,
                scenario_hash=case["scenario_hash"],
                trial_index=index,
                configured=harness is not None,
                attack_configured=bool(harness and harness.attacks),
                case_kind=(
                    "mixed"
                    if harness and harness.attacks and harness.faults
                    else "attack"
                    if harness and harness.attacks
                    else "fault"
                    if harness and harness.faults
                    else "benign"
                    if harness and harness.benign_control
                    else "empty"
                ),
                materialized=trial is not None,
                trial_id=trial["trial_id"] if trial else None,
                scoring_id=r.scoring_id if r else None,
                revision=revisions.get(r.scoring_id) if r else None,
                classification="planned_not_materialized",
                completed=False,
                execution_status=None,
                resume_eligible=None,
                eligible=bool(r and r.eligible),
                exposure=None,
                outcome=None,
                unsupported=False,
            )
            if trial:
                slot["classification"] = "materialized_unscored"
                capture = trial.get("evidence")
                facts = execution_facts(
                    capture, evidence_hash=trial.get("evidence_hash"), verify_hash=True
                )
                slot.update(
                    completed=facts["completed"],
                    execution_status=facts["status"],
                    resume_eligible=facts["resume_eligible"],
                    evidence_errors=facts["errors"],
                    classification=facts["classification"],
                )
                if r:
                    if r.scenario_hash != case["scenario_hash"]:
                        raise ValueError("selected score/scenario conflict")
                    resolution = resolve_trial(
                        r,
                        facts=facts,
                        expected_ids=[a.injection_id for a in harness.attacks] if harness else [],
                    )
                    slot.update(
                        resolution=resolution,
                        exposure=resolution["exposure"],
                        outcome=resolution["outcome"],
                        classification=resolution["classification"],
                    )
                    if (
                        resolution["outcome"] is None
                        and facts["classification"]
                        in {
                            "missing_execution",
                            "malformed_execution",
                            "incomplete_execution",
                            "incomplete_resumable",
                            "interrupted_nonresumable",
                        }
                        and not resolution["infrastructure_excluded"]
                    ):
                        slot["classification"] = facts["classification"]
                    slot["unsupported"] = any(
                        "unsupported" in g["categories"] for g in resolution["objectives"]
                    )
            slots.append(slot)
    if set(materialized) - seen:
        raise ValueError("materialized trial outside frozen plan")
    return dict(
        schema_version="1.6",
        plan_status="verified",
        manifest_hash=experiment["manifest_hash"],
        planned_trials=len(slots),
        materialized_trials=sum(s["materialized"] for s in slots),
        selected_scores=sum(s["scoring_id"] is not None for s in slots),
        unmaterialized_trials=sum(not s["materialized"] for s in slots),
        unscored_trials=sum(s["materialized"] and s["scoring_id"] is None for s in slots),
        completed_trials=sum(s["completed"] for s in slots),
        eligible_trials=sum(s["eligible"] for s in slots),
        excluded_trials=sum(s["scoring_id"] is not None and not s["eligible"] for s in slots),
        metadata_unavailable_trials=0,
        classification_counts=dict(Counter(s["classification"] for s in slots)),
        slots=slots,
    )


def security_summary(results, legacy, experiment=None, trials=(), revisions=None):
    pop = population(experiment, trials, results, revisions)
    slots = [s for s in pop["slots"] if s["attack_configured"]]
    exposed = [s for s in slots if s["exposure"] is True]
    unexposed = [s for s in slots if s["exposure"] is False]
    known = [s for s in exposed if s["outcome"] is not None]
    available = pop["plan_status"] == "verified"
    success = sum(s["outcome"] is True for s in known)
    failure = len(known) - success
    denominator = len(slots) - len(unexposed)
    coverage = proportion(len(known), denominator, "no_exposure_eligible_trials")
    if not available:
        coverage.update(
            value=None, denominator=None, status="unavailable", reason="experiment_plan_unavailable"
        )
    legacy.update(
        configured_trials=sum(s["configured"] for s in pop["slots"]) if available else None,
        population=pop,
        trial_metadata_unavailable=pop["metadata_unavailable_trials"],
        case_distribution=dict(Counter(s["case_kind"] for s in pop["slots"] if s["configured"])),
    )
    legacy["attack_outcome_coverage"] = dict(
        schema_version="1.6",
        configured_attack_trials=len(slots) if available else None,
        exposed_trials=len(exposed),
        unexposed_controls=len(unexposed),
        determinate_trials=len(known),
        unknown_trials=denominator - len(known) if available else None,
        unverified_exposure_trials=len(slots) - len(exposed) - len(unexposed)
        if available
        else None,
        measured_successes=success,
        measured_failures=failure,
        unsupported_trials=sum(s["unsupported"] for s in slots),
        coverage=coverage,
        attack_success=attack_metric([s["resolution"] for s in slots if "resolution" in s]),
        trial_metadata_unavailable=pop["metadata_unavailable_trials"],
        units="planned trial slots",
    )
    return legacy
