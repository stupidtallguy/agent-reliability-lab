"""Planned-trial coverage independent of whether objective scoring was reached."""

from agent_reliability_lab.evaluation.metrics import proportion


def coverage_summary(results, summary):
    plans = [(r, r.experimental.get("planned_trial", {})) for r in results]
    known = [(r, p) for r, p in plans if p.get("status") == "known"]
    missing = len(plans) - len(known)
    attacked = [r for r, p in known if p["attack_count"] > 0]
    exposed = [r for r in attacked if r.experimental.get("verified_attack_exposure") is True]
    unexposed = [r for r in attacked if r.experimental.get("verified_attack_exposure") is False]
    determinate = [r for r in exposed if r.attacker_success is not None]
    unknown = [r for r in attacked if r not in unexposed and r not in determinate]
    unsupported = [
        r
        for r in unknown
        if any(
            any(
                c in {"unsupported_arguments", "target_intent_unverifiable"}
                for c in goal.get("attribution", {}).get("diagnostic_categories", [])
            )
            for goal in r.experimental.get("objectives", [])
        )
    ]
    configured = sum(bool(p["configured_trial"]) for _, p in known)
    coverage = proportion(
        len(determinate), len(attacked) - len(unexposed), "no_exposure_eligible_trials"
    )
    if missing:
        coverage.update(
            value=None,
            denominator=None,
            status="unavailable",
            reason="trial_plan_metadata_unavailable",
        )
    summary["configured_trials"] = configured if not missing else None
    summary["configured_trials_known_minimum"] = configured
    summary["trial_metadata_unavailable"] = missing
    summary["attack_outcome_coverage"] = {
        "configured_attack_trials": len(attacked) if not missing else None,
        "configured_attack_trials_known_minimum": len(attacked),
        "exposed_trials": len(exposed),
        "unexposed_controls": len(unexposed),
        "unverified_exposure_trials": len(attacked) - len(exposed) - len(unexposed),
        "evaluated_trials": sum(
            bool(r.experimental.get("objectives"))
            and r.scoring_provenance.get("effective_evaluator_version") == "1.4.0"
            for r in attacked
        ),
        "determinate_trials": len(determinate),
        "measured_successes": sum(r.attacker_success is True for r in determinate),
        "measured_failures": sum(r.attacker_success is False for r in determinate),
        "unknown_trials": len(unknown),
        "unsupported_trials": len(unsupported),
        "trial_metadata_unavailable": missing,
        "coverage": coverage,
        "attack_success": proportion(
            sum(r.attacker_success is True for r in determinate),
            len(determinate),
            "no_determinate_attack_outcomes",
        ),
        "units": "trials; unsupported is a subset of unknown",
    }
    return summary
