"""Tests for historical climate analysis calculations."""

import pytest

from weather.climate_analysis import (
    calculate_anomaly,
    calculate_pearson_correlation,
)


@pytest.mark.parametrize(
    ("value", "baseline", "expected"),
    [(72.0, 70.0, 2.0), (None, 70.0, None), (72.0, None, None)],
)
def test_calculate_anomaly(value, baseline, expected):
    assert calculate_anomaly(value, baseline) == expected


def test_calculate_pearson_correlation_uses_overlapping_values_only():
    result = calculate_pearson_correlation(
        [(1.0, 2.0), (None, 8.0), (2.0, 4.0), (3.0, 6.0)]
    )

    assert result.value == pytest.approx(1.0)
    assert result.sample_count == 3


def test_calculate_pearson_correlation_returns_negative_relationship():
    result = calculate_pearson_correlation([(1.0, 6.0), (2.0, 4.0), (3.0, 2.0)])

    assert result.value == pytest.approx(-1.0)
    assert result.sample_count == 3


def test_calculate_pearson_correlation_requires_three_overlapping_values():
    result = calculate_pearson_correlation([(1.0, 2.0), (None, 3.0), (2.0, 4.0)])

    assert result.value is None
    assert result.sample_count == 2


def test_calculate_pearson_correlation_returns_none_for_zero_variance():
    result = calculate_pearson_correlation([(1.0, 2.0), (1.0, 4.0), (1.0, 6.0)])

    assert result.value is None
    assert result.sample_count == 3
