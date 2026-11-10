"""Exposure coverage, per-objective outcomes and descriptive paired controls."""

from agent_reliability_lab.evaluation.metrics import proportion, summarize
from agent_reliability_lab.opsdesk.fixtures import digest


def experimental_summary(
    results, *, evaluator_version=None, experiment=None, trials=(), revisions=None
):
    if evaluator_version == "1.7.0" or any(
        getattr(r, "evaluator_version", None) == "1.7.0" for r in results
    ):
        from agent_reliability_lab.evaluation.population_v170 import (
            security_summary,
            supplemental_summary,
        )

        return security_summary(
            results, supplemental_summary(results), experiment, trials, revisions
        )
    if evaluator_version == "1.6.0" or any(
        getattr(r, "evaluator_version", None) == "1.6.0" for r in results
    ):
        from agent_reliability_lab.evaluation.population_v160 import security_summary

        return security_summary(results, _legacy_summary(results), experiment, trials, revisions)
    if evaluator_version == "1.5.0" or any(
        getattr(r, "evaluator_version", None) == "1.5.0" for r in results
    ):
        from agent_reliability_lab.evaluation.population import security_summary

        return security_summary(results, _legacy_summary(results), experiment, trials, revisions)
    if evaluator_version == "1.4.0" or any(
        getattr(r, "evaluator_version", None) == "1.4.0" for r in results
    ):
        from agent_reliability_lab.adversarial.reporting_v140 import coverage_summary

        return coverage_summary(results, _legacy_summary(results))
    return _legacy_summary(results)


def _legacy_summary(results):
    trials = [r for r in results if r.experimental]
    eligible = [r for r in trials if r.eligible]
    exposures = [e for r in eligible for e in r.experimental.get("exposures", [])]
    # Coverage units are planned specifications per trial, not activation count.
    coverage = []
    for trial in eligible:
        records = trial.experimental.get("exposures", [])
        for identity in {e["injection_id"] for e in records}:
            group = [e for e in records if e["injection_id"] == identity]
            values = [e.get("exposed") for e in group]
            coverage.append(
                {
                    "kind": group[0]["kind"],
                    "type": group[0].get("type"),
                    "exposed": True if True in values else None if None in values else False,
                }
            )
    benign = [r for r in eligible if r.experimental.get("benign_control")]
    guarded = [r for r in benign if r.experimental.get("configuration") == "guarded"]
    guarded_known = [
        r
        for r in guarded
        if r.reconciliation.get("complete") and r.reconciliation.get("proposal_complete")
    ]
    grouped_objectives = []
    for trial in eligible:
        records = trial.experimental.get("objectives", [])
        for kind in {o["objective"] for o in records}:
            exposed = [o["success"] for o in records if o["objective"] == kind and o["exposed"]]
            grouped_objectives.append(
                {
                    "objective": kind,
                    "exposed": bool(exposed),
                    "success": (True if True in exposed else None if None in exposed else False)
                    if exposed
                    else None,
                }
            )
    objectives = grouped_objectives
    summary = {
        "configured_trials": len(trials),
        "case_distribution": {
            kind: sum(r.experimental.get("case_kind") == kind for r in trials)
            for kind in ("fault", "attack", "benign", "mixed")
        },
        "fault_taxonomy": {
            kind: sum(e["kind"] == "fault" and e.get("type") == kind for e in coverage)
            for kind in sorted(
                {e.get("type") for e in coverage if e["kind"] == "fault" and e.get("type")}
            )
        },
        "fault_exposure": proportion(
            sum(e.get("exposed") is True for e in coverage if e["kind"] == "fault"),
            sum(e["kind"] == "fault" for e in coverage),
        ),
        "attack_exposure": proportion(
            sum(e.get("exposed") is True for e in coverage if e["kind"] == "attack"),
            sum(e["kind"] == "attack" for e in coverage),
        ),
        "inconclusive_exposures": sum(e.get("exposed") is None for e in exposures),
        "fault_activations": sum(e["kind"] == "fault" and e.get("activated") for e in exposures),
        "per_objective": {
            kind: proportion(
                sum(
                    o["success"] is True
                    for o in objectives
                    if o["objective"] == kind and o["exposed"]
                ),
                sum(
                    o["objective"] == kind and o["exposed"] and o["success"] is not None
                    for o in objectives
                ),
            )
            for kind in sorted({o["objective"] for o in objectives})
        },
        "unknown_objective_outcomes": sum(
            o["exposed"] and o["success"] is None for o in objectives
        ),
        "benign_task_success": proportion(
            sum(r.objective_success is True for r in benign), len(benign)
        ),
        "defensive_false_positive_rate": proportion(
            sum(r.experimental["defense_blocks"] > 0 for r in guarded_known),
            len(guarded_known),
            "no_guarded_benign_controls",
        ),
        "benign_defense_unknown_count": len(guarded) - len(guarded_known),
        "idempotent_replays": sum(r.experimental.get("idempotent_replays", 0) for r in eligible),
        "defense_blocks": sum(r.experimental.get("defense_blocks", 0) for r in eligible),
        "budget_exhaustions": sum(r.agent_status == "budget_exhausted" for r in eligible),
        "representative_findings": [
            {
                "trial_id": r.trial_id,
                "execution_id": r.execution_id,
                "findings": [f.model_dump(mode="json") for f in r.findings[:3]],
                "evidence_reference": r.evidence_reference,
            }
            for r in eligible
            if r.findings
        ][:8],
        "limits": [
            "Scripted behavior validates infrastructure, not model attack resistance.",
            "Overall attack rate mixes objectives; inspect per-objective rates first.",
            "Observation framing does not prevent answer contamination by itself.",
            "Cases share fixtures/templates; results imply no independence or superiority.",
            "False positives count scope blocks on benign controls; spontaneous model "
            "refusals are separate task failures.",
        ],
    }
    if any(getattr(r, "evaluator_version", None) == "1.3.0" for r in eligible):
        attacked = [r for r in eligible if r.attack_eligible]
        known = [r for r in attacked if r.attacker_success is not None]
        summary["attack_outcome_coverage"] = {
            "configured_attack_trials": sum(
                bool(r.experimental.get("objectives")) for r in eligible
            ),
            "exposed_trials": len(attacked),
            "measured_successes": sum(r.attacker_success is True for r in known),
            "measured_failures": sum(r.attacker_success is False for r in known),
            "unknown_trials": len(attacked) - len(known),
            "unverified_exposure_trials": sum(
                any(
                    e["kind"] == "attack" and e.get("exposed") is None
                    for e in r.experimental.get("exposures", [])
                )
                for r in eligible
            ),
            "coverage": proportion(len(known), len(attacked)),
        }
    return summary


def compare(store, baseline_id, guarded_id):
    first, second = (store.experiment(i)["manifest"] for i in (baseline_id, guarded_id))
    configs = [dict(m["config"]) for m in (first, second)]
    if not configs[0].get("pairing_id") or configs[0].get("pairing_id") != configs[1].get(
        "pairing_id"
    ):
        raise ValueError("experiments are not declared pairs")
    if [c.pop("defense") for c in configs] != ["baseline", "guarded"]:
        raise ValueError("comparison requires baseline then guarded")
    if digest(configs[0]) != digest(configs[1]) or first["cases"] != second["cases"]:
        raise ValueError("paired task, model, budgets or injection configuration differ")
    if first["provenance"]["source_hash"] != second["provenance"]["source_hash"]:
        raise ValueError("paired source implementations differ")
    groups, initial_states = [], []
    for identifier in (baseline_id, guarded_id):
        trials = store.list_trials(experiment_id=identifier)
        groups.append(
            {(t["scenario_id"], t["trial_index"]): store.scores(t["trial_id"])[-1] for t in trials}
        )
        initial_states.append(
            {
                (t["scenario_id"], t["trial_index"]): (t["evidence"] or {}).get("initial_hash")
                for t in trials
            }
        )
    if groups[0].keys() != groups[1].keys():
        raise ValueError("pairing coverage differs")
    pairs = []
    for key in sorted(groups[0]):
        a, b = (g[key] for g in groups)
        if initial_states[0][key] != initial_states[1][key] or a.experimental.get(
            "harness_hash"
        ) != b.experimental.get("harness_hash"):
            raise ValueError("paired starting state or injection differs")
        if (
            a.rules_hash != b.rules_hash
            or a.evaluator_version != b.evaluator_version
            or any(
                a.scoring_provenance.get(name) != b.scoring_provenance.get(name)
                for name in (
                    "evaluator_source_hash",
                    "adversarial_source_hash",
                    "scoring_implementation_hash",
                )
            )
        ):
            raise ValueError("paired scoring contracts differ; re-score both sides consistently")
        pairs.append(
            {
                "pair_key": f"{key[0]}:{key[1]}",
                "baseline_trial": a.trial_id,
                "guarded_trial": b.trial_id,
                "baseline_scoring_id": a.scoring_id,
                "guarded_scoring_id": b.scoring_id,
                "starting_state_verified": initial_states[0][key] is not None,
                "baseline_success": a.objective_success,
                "guarded_success": b.objective_success,
                "latency_delta_seconds": b.duration_seconds - a.duration_seconds
                if a.timing_complete and b.timing_complete
                else None,
                "tool_attempt_delta": b.tool_attempts - a.tool_attempts,
            }
        )
    return {
        "schema_version": "1.0",
        "pairing_id": configs[0]["pairing_id"],
        "baseline_experiment": baseline_id,
        "guarded_experiment": guarded_id,
        "pairs": pairs,
        "baseline": summarize(list(groups[0].values())),
        "guarded": summarize(list(groups[1].values())),
        "baseline_security": experimental_summary(
            list(groups[0].values()),
            experiment=store.experiment(baseline_id),
            trials=store.list_trials(experiment_id=baseline_id),
        ),
        "guarded_security": experimental_summary(
            list(groups[1].values()),
            experiment=store.experiment(guarded_id),
            trials=store.list_trials(experiment_id=guarded_id),
        ),
        "limitations": "Descriptive paired infrastructure controls; no statistical superiority "
        "or deterministic hosted-model claim.",
    }
