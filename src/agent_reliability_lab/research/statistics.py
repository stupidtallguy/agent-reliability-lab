"""Exploratory paired summaries with family-level resampling and explicit missingness."""

import math
import random
from collections import defaultdict
from statistics import mean

from agent_reliability_lab.evaluation.statistics import wilson


def exact_mcnemar(b, c):
    if b < 0 or c < 0:
        raise ValueError("discordant counts must be nonnegative")
    n = b + c
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2**n)


def paired_summary(rows, *, seed=0, resamples=2000, independent_units_justification=None):
    if resamples < 100 or resamples > 100000:
        raise ValueError("resamples must be between 100 and 100000")
    ids = [r["pair_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate pair identity")
    complete = [
        r
        for r in rows
        if r.get("verified") is True
        and type(r.get("baseline")) is bool
        and type(r.get("guarded")) is bool
    ]
    groups, scenarios = defaultdict(list), defaultdict(list)
    for r in complete:
        if not r.get("family_id") or not r.get("scenario_id"):
            raise ValueError("verified comparisons require explicit family/scenario identity")
        delta = int(r["guarded"]) - int(r["baseline"])
        groups[r["family_id"]].append(delta)
        scenarios[r["scenario_id"]].append(delta)
    deltas = [mean(v) for v in groups.values()]
    independent = (
        bool(independent_units_justification)
        and len(complete) >= 2
        and len(groups) == len(complete)
        and len(complete) == len(rows)
    )
    b = sum(r["baseline"] and not r["guarded"] for r in complete)
    c = sum(r["guarded"] and not r["baseline"] for r in complete)
    interval = None
    if len(deltas) >= 2:
        rng = random.Random(seed)
        samples = sorted(mean(rng.choices(deltas, k=len(deltas))) for _ in range(resamples))
        interval = [
            samples[math.floor(0.025 * (resamples - 1))],
            samples[math.ceil(0.975 * (resamples - 1))],
        ]
    n, missing = len(complete), len(rows) - len(complete)
    observed = sum(int(r["guarded"]) - int(r["baseline"]) for r in complete)
    return dict(
        schema_version="1.0",
        interpretation="exploratory_descriptive",
        independent_units_justification=independent_units_justification,
        planned_pairs=len(rows),
        complete_verified_pairs=n,
        incomplete_or_unknown_pairs=missing,
        pair_coverage=n / len(rows) if rows else None,
        family_count=len(groups),
        baseline_successes=sum(r["baseline"] for r in complete),
        guarded_successes=sum(r["guarded"] for r in complete),
        paired_risk_difference=observed / n if n else None,
        family_weighted_risk_difference=mean(deltas) if deltas else None,
        cluster_bootstrap_interval=interval,
        bootstrap_seed=seed,
        bootstrap_resamples=resamples,
        interval_method="percentile_95_family_cluster_bootstrap",
        exact_mcnemar_p=exact_mcnemar(b, c) if independent else None,
        mcnemar_unavailable_reason=None
        if independent
        else "independent_complete_pairs_not_established",
        per_scenario={
            key: dict(n=len(v), risk_difference=mean(v)) for key, v in sorted(scenarios.items())
        },
        per_family={
            key: dict(n=len(v), risk_difference=mean(v)) for key, v in sorted(groups.items())
        },
        exclusion_sensitivity_bounds=[
            (observed - missing) / len(rows),
            (observed + missing) / len(rows),
        ]
        if rows
        else None,
        wilson_descriptive_guarded=wilson(sum(r["guarded"] for r in complete), n),
        warnings=[
            "Development data; no superiority or generalization claim.",
            "Wilson interval is descriptive; repeated trials are clustered.",
        ]
        + (
            ["Fewer than 20 template families; tail and interval estimates are unstable."]
            if len(groups) < 20
            else []
        ),
    )
