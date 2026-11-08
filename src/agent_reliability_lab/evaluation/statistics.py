"""Descriptive statistics; no independence or significance claims."""

import math
from statistics import NormalDist


def nearest_rank(values: list[float], probability: float = 0.95) -> float | None:
    if not 0 < probability <= 1:
        raise ValueError("probability must be in (0, 1]")
    if not values:
        return None
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("durations must be finite and nonnegative")
    return sorted(values)[math.ceil(probability * len(values)) - 1]


def wilson(successes: int, total: int, confidence: float = 0.95) -> list[float] | None:
    if not 0 <= successes <= total or not 0 < confidence < 1:
        raise ValueError("invalid proportion or confidence")
    if total == 0:
        return None
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        / denominator
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]
