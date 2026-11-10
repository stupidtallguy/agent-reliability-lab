"""Multiple outcome estimands on the same pinned, unique trial/execution pairs."""

from agent_reliability_lab.research.statistics import paired_summary

FIELDS = {
    "task_success": "objective_success",
    "attack_success": "attacker_success",
    "recovery": "recovered",
    "unauthorized_attempt": "unauthorized_attempt",
    "prohibited_effect": "unsafe",
    "defense_false_positive": None,
}


def summarize_outcomes(store, analysis, *, seed=0):
    selected = {}
    for reference in analysis["selected_scores"]:
        selected[reference["trial_id"]] = next(
            r
            for r in store.evaluations.scores(reference["trial_id"])
            if r.scoring_id == reference["scoring_id"]
        )
    outcomes = {}
    for metric, field in FIELDS.items():
        rows = []
        not_applicable = 0
        for source in analysis["rows"]:
            row = dict(source)
            pair_results = [selected.get(row[s + "_trial_id"]) for s in ("baseline", "guarded")]
            if metric in {"attack_success", "recovery", "defense_false_positive"}:

                def applicable(result, metric=metric):
                    if result is None:
                        return None
                    plan = result.experimental.get("planned_trial", {})
                    if not isinstance(plan, dict) or plan.get("status") != "known":
                        return None
                    if metric == "defense_false_positive":
                        return plan.get("benign_control")
                    count = plan.get(
                        "attack_count" if metric == "attack_success" else "fault_count"
                    )
                    if type(count) is not int:
                        return None
                    if count == 0:
                        return False
                    if metric == "attack_success":
                        return True
                    recoveries = result.experimental.get("recoveries", [])
                    if any(r.get("recoverable") is True for r in recoveries):
                        return True
                    if len(recoveries) == count and all(
                        r.get("recoverable") is False for r in recoveries
                    ):
                        return False
                    return None

                if all(applicable(r) is False for r in pair_results):
                    not_applicable += 1
                    continue
            for side in ("baseline", "guarded"):
                result = selected.get(row[side + "_trial_id"])
                eligible = result is not None and result.eligible
                if metric == "attack_success":
                    eligible = eligible and result.attack_eligible
                elif metric == "recovery":
                    eligible = eligible and result.recovery_eligible
                if metric == "defense_false_positive":
                    eligible = (
                        eligible
                        and result.experimental.get("benign_control")
                        and result.reconciliation.get("complete")
                        and result.reconciliation.get("proposal_complete")
                    )
                    row[side] = (
                        result.experimental["defense_blocks"] > 0
                        if eligible and type(result.experimental.get("defense_blocks")) is int
                        else None
                    )
                elif metric == "attack_success" and result and result.evaluator_version == "1.7.0":
                    from agent_reliability_lab.evaluation.attack_outcomes_v170 import resolve_trial

                    resolved = resolve_trial(result)
                    row[side] = (
                        resolved["outcome"]
                        if resolved["eligible"] and resolved["exposure"] is True
                        else None
                    )
                else:
                    row[side] = getattr(result, field) if eligible else None
            rows.append(row)
        summary = paired_summary(rows, seed=seed)
        summary["not_applicable_pairs"] = not_applicable
        summary["experiment_planned_pairs"] = len(analysis["rows"])
        summary["estimand"] = "guarded_minus_baseline_on_complete_eligible_pairs"
        summary["direction"] = (
            "lower_is_better"
            if metric
            in {
                "attack_success",
                "unauthorized_attempt",
                "prohibited_effect",
                "defense_false_positive",
            }
            else "higher_is_better"
        )
        outcomes[metric] = summary
    return outcomes
