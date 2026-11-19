"""Tests for historical climate analysis calculations."""

import pytest

from weather.climate_analysis import (
    build_caveats,
    calculate_anomaly,
    calculate_pearson_correlation,
    multiple_testing_summary,
    rank_analog_years,
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


def _means(index, values_by_year):
    return [
        {"index": index, "date": f"{year}-01-01", "value": value}
        for year, value in values_by_year.items()
    ]


def test_rank_analog_years_orders_by_closeness_and_limits_results():
    window_means = _means("nao", {2000 + n: float(n) for n in range(12)})

    result = rank_analog_years(window_means, {"nao": 5.2}, top=3)

    assert [entry["year"] for entry in result["years"]] == [2005, 2006, 2004]
    assert result["years"][0]["distance"] < result["years"][1]["distance"]
    assert result["indices_used"] == ["nao"]
    assert result["year_count"] == 12
    assert result["years"][0]["indices"] == {"nao": 5.0}


def test_rank_analog_years_scales_each_index_by_its_own_spread():
    # AO varies 100x more than NAO; unscaled, it would decide the ranking alone.
    years = range(2000, 2012)
    window_means = _means("nao", {y: (y - 2000) * 0.01 for y in years}) + _means(
        "ao", {y: float(y - 2000) for y in years}
    )

    result = rank_analog_years(window_means, {"nao": 0.0, "ao": 11.0}, top=2)

    # 2000 matches NAO perfectly but is far from AO; 2011 matches AO but not NAO.
    # Scaled equally, the middle of the road ranks ahead of both extremes.
    assert result["indices_used"] == ["ao", "nao"]
    assert {entry["year"] for entry in result["years"]} == {2005, 2006}


def test_rank_analog_years_only_ranks_years_with_every_index():
    window_means = _means("nao", {2000 + n: float(n) for n in range(12)}) + _means(
        "ao", {2001 + n: float(n) for n in range(11)}
    )

    result = rank_analog_years(window_means, {"nao": 3.0, "ao": 3.0}, top=20)

    assert result["year_count"] == 11
    assert 2000 not in {entry["year"] for entry in result["years"]}


def test_rank_analog_years_ignores_indices_without_a_current_value():
    window_means = _means("nao", {2000 + n: float(n) for n in range(12)}) + _means(
        "ao", {2000 + n: float(n) for n in range(12)}
    )

    result = rank_analog_years(window_means, {"nao": 4.0})

    assert result["indices_used"] == ["nao"]


@pytest.mark.parametrize(
    "window_means",
    [
        _means("nao", {2000 + n: float(n) for n in range(9)}),  # too few years
        _means("nao", {2000 + n: 1.0 for n in range(12)}),  # no spread to scale by
        [],
    ],
)
def test_rank_analog_years_returns_none_without_enough_usable_history(window_means):
    assert rank_analog_years(window_means, {"nao": 1.0}) is None


def test_rank_analog_years_needs_enough_years_in_common():
    window_means = _means("nao", {2000 + n: float(n) for n in range(10)}) + _means(
        "ao", {2005 + n: float(n) for n in range(10)}
    )

    assert rank_analog_years(window_means, {"nao": 3.0, "ao": 3.0}) is None
