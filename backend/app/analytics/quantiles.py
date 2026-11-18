"""Distribution helpers.

The product spec forbids averaging away outliers, so every surface prefers median and quartiles and reports the
sample size it used. Implemented in pure Python to keep the analytics layer dependency free.
"""

from __future__ import annotations

from collections.abc import Sequence


def quantile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated quantile; returns ``None`` for an empty sample."""
    if not values:
        return None
    if q <= 0:
        return min(values)
    if q >= 1:
        return max(values)
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def median(values: Sequence[float]) -> float | None:
    """Median of the sample."""
    return quantile(values, 0.5)


def summarize(values: Sequence[float]) -> dict[str, float | int | None]:
    """Return count/median/quartiles/mean/min/max for one sample."""
    if not values:
        return {"count": 0, "median": None, "p25": None, "p75": None, "mean": None, "min": None, "max": None}
    return {
        "count": len(values),
        "median": round(float(median(values)), 2),
        "p25": round(float(quantile(values, 0.25)), 2),
        "p75": round(float(quantile(values, 0.75)), 2),
        "mean": round(sum(values) / len(values), 2),
        "min": round(float(min(values)), 2),
        "max": round(float(max(values)), 2),
    }


def histogram(values: Sequence[float], buckets: int = 8) -> list[dict[str, float | int]]:
    """Equal-width histogram over the observed range; returns ``[]`` for an empty sample."""
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high == low:
        return [{"bucket_start": low, "bucket_end": high, "count": len(values)}]
    width = (high - low) / buckets
    counts = [0] * buckets
    for value in values:
        index = min(int((value - low) / width), buckets - 1)
        counts[index] += 1
    return [
        {
            "bucket_start": round(low + index * width, 2),
            "bucket_end": round(low + (index + 1) * width, 2),
            "count": counts[index],
        }
        for index in range(buckets)
    ]


def weighted_mean(pairs: Sequence[tuple[float, float]]) -> float | None:
    """Weighted mean of ``(value, weight)`` pairs, ignoring non-positive weights."""
    total_weight = sum(weight for _, weight in pairs if weight > 0)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in pairs if weight > 0) / total_weight
