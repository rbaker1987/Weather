"""Pure calculations used by the historical climate analysis API."""

from __future__ import annotations

from math import sqrt
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
