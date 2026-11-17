"""Pure calculations used by the historical climate analysis API."""

from __future__ import annotations

from math import atanh, erf, sqrt, tanh
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable


MINIMUM_CORRELATION_SAMPLES = 3


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
    pairs = [(left, right) for left, right in values if left is not None and right is not None]
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
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
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
    pairs = [(left, right) for left, right in values if left is not None and right is not None]
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
        slope = sum((year - year_mean) * (value - mean) for year, value in zip(years, series, strict=True)) / spread
        return [value - (mean + slope * (year - year_mean)) for year, value in zip(years, series, strict=True)]

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
