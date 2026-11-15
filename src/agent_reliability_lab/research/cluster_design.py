"""Conditional power for equal-weighted paired template clusters."""

import math
import platform
import random
from functools import lru_cache

from agent_reliability_lab.evaluation.statistics import wilson
from agent_reliability_lab.opsdesk.fixtures import digest

METHOD = "paired_discordance_beta_cluster_t_v1"
MIN_COMPLETE_CLUSTERS = 20
POWER_TARGETS = (0.8, 0.9)


@lru_cache(maxsize=4096)
def critical_t(df, alpha):
    """Invert the Student t density with composite Simpson quadrature."""
    log_factor = math.lgamma((df + 1) / 2) - math.lgamma(df / 2) - math.log(df * math.pi) / 2

    def area(bound):
        step = bound / 256

        def density(x):
            return math.exp(log_factor - (df + 1) / 2 * math.log1p(x * x / df))

        total = density(0) + density(bound)
        total += 4 * sum(density(step * j) for j in range(1, 256, 2))
        total += 2 * sum(density(step * j) for j in range(2, 256, 2))
        return total * step / 3

    lo, hi = 0.0, 8.0
    target = (1 - alpha) / 2
    for _ in range(32):
        mid = (lo + hi) / 2
        if area(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _precision(n, total, squares, alpha):
    if n < MIN_COMPLETE_CLUSTERS:
        return None
    residual = squares - total * total / n
    if residual <= 1e-12:
        return None
    return critical_t(n - 1, alpha) * math.sqrt(residual / ((n - 1) * n))


def _order_means(groups):
    if not all(groups):
        return None
    return sum(sum(values) / len(values) for values in groups) / 2


def cluster_contrast(clusters, *, alpha):
    """Versioned analysis arithmetic on planned pair differences, grouped by cluster/order.

    A null value is an unresolved or excluded planned pair. Every cluster has the
    same planned number of pairs in each order. This helper does not execute trials.
    """
    if not 0.01 <= alpha <= 0.10:
        raise ValueError("alpha outside the planned interval")
    values, lower, upper = [], [], []
    missing = 0
    for orders in clusters:
        if (
            len(orders) != 2
            or not orders[0]
            or len(orders[0]) != len(orders[1])
            or any(
                type(x) is not int or x not in {-1, 0, 1}
                for order in orders
                for x in order
                if x is not None
            )
        ):
            raise ValueError("cluster slots require two balanced orders and paired differences")
        observed = [[x for x in order if x is not None] for order in orders]
        contrast = _order_means(observed)
        if contrast is not None:
            values.append(contrast)
        missing += sum(len(a) - len(b) for a, b in zip(orders, observed, strict=True))
        lower.append(_order_means([[x if x is not None else -1 for x in o] for o in orders]))
        upper.append(_order_means([[x if x is not None else 1 for x in o] for o in orders]))
    n, total = len(values), sum(values)
    margin = _precision(n, total, sum(x * x for x in values), alpha)
    estimate = total / n if n else None
    return dict(
        planned_clusters=len(clusters),
        complete_clusters=n,
        missing_or_excluded_pairs=missing,
        estimate=estimate,
        interval=[estimate - margin, estimate + margin] if margin is not None else None,
        interval_reason=None if margin is not None else "too_few_clusters_or_zero_variance",
        sensitivity_bounds=[sum(lower) / len(lower), sum(upper) / len(upper)] if lower else None,
    )


def _simulated_cluster(rng, scenario, effect):
    if rng.random() < scenario.cluster_dropout:
        return None, 0
    mean_sign = (1 + effect / scenario.discordance) / 2
    rho = scenario.cluster_sign_icc
    if rho:
        concentration = (1 - rho) / rho
        positive = rng.betavariate(mean_sign * concentration, (1 - mean_sign) * concentration)
    else:
        positive = mean_sign
    order_values = ([], [])
    pair_loss = scenario.pair_missing + scenario.pair_excluded
    for order in order_values:
        for _ in range(scenario.repetitions_per_cluster // 2):
            if rng.random() >= pair_loss:
                draw = rng.random()
                order.append(
                    1
                    if draw < scenario.discordance * positive
                    else -1
                    if draw < scenario.discordance
                    else 0
                )
    return _order_means(order_values), sum(map(len, order_values))


def _simulate(design, scenario, effect):
    seed = int(digest([design.seed, scenario.identity, effect])[:16], 16)
    rng = random.Random(seed)
    counts = [[0, 0, 0, 0] for _ in design.cluster_grid]
    for _ in range(design.simulations):
        usable = pairs = 0
        total = squares = 0.0
        start = 0
        for end, row in zip(design.cluster_grid, counts, strict=True):
            for _ in range(start, end):
                value, observed = _simulated_cluster(rng, scenario, effect)
                pairs += observed
                if value is not None:
                    usable += 1
                    total += value
                    squares += value * value
            start = end
            margin = _precision(usable, total, squares, design.alpha)
            row[0] += margin is not None and abs(total / usable) > margin
            row[1] += margin is not None
            row[2] += usable
            row[3] += pairs
    return seed, counts


def plan_power(design):
    """Report conditional designs; do not promote illustrative assumptions to a study size."""
    report = dict(
        method=METHOD,
        python_version=platform.python_version(),
        inputs=design.model_dump(mode="json"),
        targets=list(POWER_TARGETS),
        minimum_complete_clusters=MIN_COMPLETE_CLUSTERS,
        inference="two_sided_student_t",
        assumption_model="fixed_discordance_beta_random_sign_mcar",
        allocation="equal_repetitions_in_each_order_no_systematic_order_effect",
        simulations_are_observations=False,
        results=[],
    )
    minimum = design.minimum_meaningful_difference
    if minimum is None or not design.scenarios:
        return dict(
            **report,
            status="insufficient_assumptions",
            reason="minimum_effect_and_explicit_scenarios_required",
        )
    justified = design.planning_basis == "externally_justified" and bool(design.justification)
    at_minimum = any(math.isclose(row.expected_difference, minimum) for row in design.scenarios)
    for scenario in design.scenarios:
        alt_seed, alternative = _simulate(design, scenario, scenario.expected_difference)
        null_seed, null = _simulate(design, scenario, 0.0)
        rows = []
        for planned, alt, calibration in zip(design.cluster_grid, alternative, null, strict=True):
            n = design.simulations
            power_bound = wilson(alt[0], n)
            null_bound = wilson(calibration[0], n)
            rows.append(
                dict(
                    planned_clusters=planned,
                    planned_pairs=planned * scenario.repetitions_per_cluster,
                    mean_usable_clusters=alt[2] / n,
                    mean_observed_pairs=alt[3] / n,
                    power=alt[0] / n,
                    power_monte_carlo_interval=power_bound,
                    null_rejection=calibration[0] / n,
                    null_monte_carlo_interval=null_bound,
                    unavailable_analysis_rate=1 - alt[1] / n,
                    null_calibrated=null_bound[1] <= design.alpha + design.maximum_null_inflation,
                )
            )
        conditional = {
            str(target): next(
                (
                    row["planned_clusters"]
                    for row in rows
                    if row["null_calibrated"] and row["power_monte_carlo_interval"][0] >= target
                ),
                None,
            )
            for target in POWER_TARGETS
        }
        delta, q = scenario.expected_difference, scenario.discordance
        report["results"].append(
            dict(
                scenario=scenario.identity,
                alternative_seed=alt_seed,
                null_seed=null_seed,
                marginal_difference_icc=(q * q - delta * delta)
                * scenario.cluster_sign_icc
                / (q - delta * delta),
                conditional_first_grid_clusters=conditional,
                minimum_effect_scenario=math.isclose(delta, minimum),
                rows=rows,
            )
        )
    minimum_rows = [r for r in report["results"] if r["minimum_effect_scenario"]]
    robust = {}
    for target in POWER_TARGETS:
        robust[str(target)] = next(
            (
                count
                for index, count in enumerate(design.cluster_grid)
                if minimum_rows
                and all(
                    item["rows"][index]["null_calibrated"]
                    and item["rows"][index]["power_monte_carlo_interval"][0] >= target
                    for item in minimum_rows
                )
            ),
            None,
        )
    return dict(
        **report,
        status="conditional_design_only"
        if justified and at_minimum
        else "insufficient_assumptions",
        reason=None
        if justified and at_minimum
        else "externally_justified_minimum_effect_scenario_required",
        planning_clusters=robust if justified and at_minimum else None,
    )
