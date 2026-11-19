"""Pure calculations used by the historical climate analysis API."""

from __future__ import annotations

from math import atanh, erf, sqrt, tanh
from statistics import fmean, pstdev
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable


MINIMUM_CORRELATION_SAMPLES = 3
# Below this many samples a confidence interval is not reported at all.
MINIMUM_INTERVAL_SAMPLES = 4
# Fewer completed years than this makes any single relationship exploratory.
MIN_RELIABLE_SAMPLES = 30
# An "unusual week" relationship rests on only the event years, so it needs a floor.
MIN_RELIABLE_EVENTS = 5
SIGNIFICANCE_LEVEL = 0.05
# Analog ranking needs enough years for the "typical spread" of each index to mean anything.
MIN_ANALOG_YEARS = 10
DEFAULT_ANALOG_COUNT = 10


class CorrelationResult(NamedTuple):
    """A Pearson correlation and the number of matched observations."""

    value: float | None
    sample_count: int


def calculate_anomaly(value: float | None, baseline: float | None) -> float | None:
    """Return a value's departure from its baseline when both are available."""
    if value is None or baseline is None:
        return None
    return value - baseline


def calculate_pearson_correlation(
    values: Iterable[tuple[float | None, float | None]],
) -> CorrelationResult:
    """Calculate Pearson correlation using only pairs with values on both dates."""
    pairs = [
        (left, right)
        for left, right in values
        if left is not None and right is not None
    ]
    sample_count = len(pairs)
    if sample_count < MINIMUM_CORRELATION_SAMPLES:
        return CorrelationResult(value=None, sample_count=sample_count)

    left_values, right_values = zip(*pairs, strict=True)
    left_mean = sum(left_values) / sample_count
    right_mean = sum(right_values) / sample_count
    numerator = sum(
        (left - left_mean) * (right - right_mean)
        for left, right in zip(left_values, right_values, strict=True)
    )
    left_deviation = sum((left - left_mean) ** 2 for left in left_values)
    right_deviation = sum((right - right_mean) ** 2 for right in right_values)
    denominator = sqrt(left_deviation * right_deviation)
    if denominator == 0:
        return CorrelationResult(value=None, sample_count=sample_count)

    return CorrelationResult(value=numerator / denominator, sample_count=sample_count)


def _ranks(values: list[float]) -> list[float]:
    """Return average ranks (1-based), handling ties."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while (
            end + 1 < len(order) and values[order[end + 1]] == values[order[position]]
        ):
            end += 1
        average = (position + end) / 2 + 1
        for item in order[position : end + 1]:
            ranks[item] = average
        position = end + 1
    return ranks


def calculate_spearman_correlation(
    values: Iterable[tuple[float | None, float | None]],
) -> CorrelationResult:
    """Rank correlation, robust to outliers and non-linear monotonic links."""
    pairs = [
        (left, right)
        for left, right in values
        if left is not None and right is not None
    ]
    if len(pairs) < MINIMUM_CORRELATION_SAMPLES:
        return CorrelationResult(value=None, sample_count=len(pairs))
    left_ranks = _ranks([float(left) for left, _ in pairs])
    right_ranks = _ranks([float(right) for _, right in pairs])
    return calculate_pearson_correlation(zip(left_ranks, right_ranks, strict=True))


def detrend_by_year(
    rows: Iterable[tuple[float | None, float | None, int]],
) -> list[tuple[float, float]]:
    """Remove each series' linear trend over year so shared trends do not inflate r."""
    complete = [(x, y, year) for x, y, year in rows if x is not None and y is not None]
    if len(complete) < MINIMUM_CORRELATION_SAMPLES:
        return []
    years = [float(year) for _, _, year in complete]
    year_mean = sum(years) / len(years)
    spread = sum((year - year_mean) ** 2 for year in years)

    def residuals(series: list[float]) -> list[float]:
        mean = sum(series) / len(series)
        if spread == 0:
            return [value - mean for value in series]
        slope = (
            sum(
                (year - year_mean) * (value - mean)
                for year, value in zip(years, series, strict=True)
            )
            / spread
        )
        return [
            value - (mean + slope * (year - year_mean))
            for year, value in zip(years, series, strict=True)
        ]

    return list(
        zip(
            residuals([float(x) for x, _, _ in complete]),
            residuals([float(y) for _, y, _ in complete]),
            strict=True,
        )
    )


def correlation_significance(
    value: float | None, sample_count: int
) -> dict[str, float | None]:
    """Two-sided p-value and 95% CI for r via the Fisher z transform."""
    empty = {"p_value": None, "ci_low": None, "ci_high": None}
    if value is None or sample_count < 4:
        return empty
    clipped = max(-0.999999, min(0.999999, value))
    z_score = atanh(clipped)
    standard_error = 1 / sqrt(sample_count - 3)
    z_stat = abs(z_score) / standard_error
    p_value = 1 - erf(z_stat / sqrt(2))
    return {
        "p_value": p_value,
        "ci_low": tanh(z_score - 1.959964 * standard_error),
        "ci_high": tanh(z_score + 1.959964 * standard_error),
    }


def reliability_warnings(
    sample_count: int, event_count: int | None = None
) -> list[str]:
    """Codes describing why a correlation should be read with caution.

    ``too_few_samples``: no confidence interval can be computed.
    ``few_samples``: fewer than ``MIN_RELIABLE_SAMPLES`` samples.
    ``few_events``: an event relationship built on fewer than ``MIN_RELIABLE_EVENTS``
    event years.
    """
    warnings = []
    if sample_count < MINIMUM_INTERVAL_SAMPLES:
        warnings.append("too_few_samples")
    elif sample_count < MIN_RELIABLE_SAMPLES:
        warnings.append("few_samples")
    if event_count is not None and event_count < MIN_RELIABLE_EVENTS:
        warnings.append("few_events")
    return warnings


def multiple_testing_summary(results: Iterable[dict]) -> dict[str, float | int]:
    """How many tests ran, how many look significant, and how many chance predicts.

    Running many correlations guarantees some pass p < 0.05 by luck, so the page
    shows the expected number of false positives next to the observed count.
    """
    p_values = [r["p_value"] for r in results if r.get("p_value") is not None]
    return {
        "tests": len(p_values),
        "significant": sum(1 for p in p_values if p < SIGNIFICANCE_LEVEL),
        "expected_by_chance": round(len(p_values) * SIGNIFICANCE_LEVEL, 1),
    }


def build_caveats(
    year_count: int,
    summary: dict[str, float | int],
    monthly_indices: Iterable[str] = (),
) -> list[str]:
    """Plain-language caveats to show alongside the results."""
    caveats = []
    if year_count < MIN_RELIABLE_SAMPLES:
        caveats.append(
            f"Only {year_count} completed years are available for this date, "
            "so these relationships are exploratory."
        )
    if summary["tests"]:
        caveats.append(
            f"{summary['significant']} of {summary['tests']} relationships look "
            f"significant (p < {SIGNIFICANCE_LEVEL}); about "
            f"{summary['expected_by_chance']:g} would be expected by chance alone."
        )
    monthly = sorted(monthly_indices)
    if monthly:
        names = ", ".join(key.upper() for key in monthly)
        caveats.append(
            f"{names} is published monthly, so one value is used for every day "
            "in the week."
        )
    return caveats


def rank_analog_years(
    window_means: Iterable[dict],
    current: dict[str, float],
    top: int = DEFAULT_ANALOG_COUNT,
) -> dict | None:
    """Rank past years by how closely their index state matches ``current``.

    ``window_means`` is the per-year, per-index centered-window mean already computed for
    the analysis ({"index", "date", "value"}); ``current`` maps index key to its latest
    published value. Each index is scaled by its own year-to-year spread so no index
    dominates, and a year's distance is the root-mean-square scaled difference over the
    indices used. Only years with every used index are ranked. Returns None when there
    are too few comparable years.
    """
    by_index: dict[str, dict[int, float]] = {}
    for item in window_means:
        if item["index"] not in current:
            continue
        year = int(str(item["date"])[:4])
        by_index.setdefault(item["index"], {})[year] = item["value"]

    spread = {
        key: pstdev(values.values())
        for key, values in by_index.items()
        if len(values) >= MIN_ANALOG_YEARS
    }
    used = sorted(key for key, value in spread.items() if value > 0)
    if not used:
        return None
    years = sorted(set.intersection(*(set(by_index[key]) for key in used)))
    if len(years) < MIN_ANALOG_YEARS:
        return None

    ranked = []
    for year in years:
        squared = [
            ((by_index[key][year] - current[key]) / spread[key]) ** 2 for key in used
        ]
        ranked.append(
            {
                "year": year,
                "distance": sqrt(fmean(squared)),
                "indices": {key: by_index[key][year] for key in used},
            }
        )
    ranked.sort(key=lambda item: item["distance"])
    return {
        "indices_used": used,
        "year_count": len(years),
        "years": ranked[:top],
    }
