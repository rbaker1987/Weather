"""Tests for historical climate analysis calculations."""

import pytest

from weather.climate_analysis import (
    build_caveats,
    calculate_anomaly,
    calculate_pearson_correlation,
    multiple_testing_summary,
    reliability_warnings,
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


@pytest.mark.parametrize(
    ("samples", "events", "expected"),
    [
        (75, None, []),
        (75, 8, []),
        (29, None, ["few_samples"]),
        (30, None, []),
        (3, None, ["too_few_samples"]),
        (75, 4, ["few_events"]),
        (10, 2, ["few_samples", "few_events"]),
        (2, 1, ["too_few_samples", "few_events"]),
    ],
)
def test_reliability_warnings(samples, events, expected):
    assert reliability_warnings(samples, events) == expected


def test_multiple_testing_summary_counts_significant_and_expected_by_chance():
    results = [
        {"p_value": 0.01},
        {"p_value": 0.049},
        {"p_value": 0.05},
        {"p_value": 0.9},
        {"p_value": None},
        {},
    ]

    assert multiple_testing_summary(results) == {
        "tests": 4,
        "significant": 2,
        "expected_by_chance": 0.2,
    }


def test_multiple_testing_summary_handles_no_tests():
    assert multiple_testing_summary([]) == {
        "tests": 0,
        "significant": 0,
        "expected_by_chance": 0,
    }


def test_build_caveats_describes_each_limitation():
    summary = {"tests": 24, "significant": 3, "expected_by_chance": 1.2}

    caveats = build_caveats(12, summary, ["oni"])

    assert "Only 12 completed years" in caveats[0]
    assert "3 of 24" in caveats[1] and "1.2 would be expected" in caveats[1]
    assert caveats[2].startswith("ONI is published monthly")


def test_build_caveats_is_empty_when_there_is_nothing_to_flag():
    summary = {"tests": 0, "significant": 0, "expected_by_chance": 0}

    assert build_caveats(75, summary) == []
