"""Tests for model precipitation classification and aggregation."""

from datetime import datetime, timedelta, timezone

import pytest

from weather.views import ModelDetailView


class TestPrecipitationLogic:
    def test_classification_handles_empty_and_missing_surface_data(self):
        assert ModelDetailView._classify_precip_types({}) == ([], [])
        assert ModelDetailView._classify_precip_types({"temperature_2m": [None]}) == (
            ["unknown"],
            [1.0],
        )

    @pytest.mark.parametrize(
        ("temperature", "expected_type", "minimum_slr"),
        [(20, "snow", 6.0), (40, "rain", 1.0), (60, "rain", 1.0)],
    )
    def test_classifies_simple_surface_conditions(
        self, temperature, expected_type, minimum_slr
    ):
        types, slrs = ModelDetailView._classify_precip_types(
            {"temperature_2m": [temperature], "precipitation": [1]}
        )

        assert types == [expected_type]
        assert slrs[0] >= minimum_slr

    def test_classification_uses_native_probability_signals(self):
        types, slrs = ModelDetailView._classify_precip_types(
            {
                "temperature_2m": [20, 60, 35, 35],
                "rain_probability": [0, 80, 10, 10],
                "snowfall_probability": [0, 10, 80, 10],
                "freezing_rain_probability": [0, 0, 0, 80],
                "ice_pellets_probability": [0, 0, 0, 0],
            }
        )

        assert types == ["snow", "rain", "sleet", "sleet"]
        assert slrs[0:2] == [12.0, 1.0]
        assert all(slr > 0 for slr in slrs[2:])

    def test_aggregate_precipitation_applies_slr_and_defaults(self):
        first = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
        second = first + timedelta(hours=1)
        hourly = {
            "time": [first.isoformat(), second.isoformat()],
            "precipitation": [1.0, 2.0],
            "precip_type": ["snow", "rain"],
            "snow_liquid_ratio": [10.0, 0],
        }

        result = ModelDetailView.aggregate_precip_by_6hour(
            hourly, [second.isoformat(), "invalid"]
        )

        assert result[second.isoformat()] == {
            "snow": 10.0,
            "sleet": 0.0,
            "freezing_rain": 0.0,
            "rain": 2.0,
            "total": 12.0,
        }

    def test_aggregate_precipitation_handles_empty_inputs(self):
        assert ModelDetailView.aggregate_precip_by_6hour({}, []) == {}
        assert ModelDetailView.aggregate_precip_by_6hour(
            {"precipitation": [1], "precip_type": ["rain"]}, ["bad"]
        ) == {}
