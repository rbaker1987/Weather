"""Tests for model agreement (spread) computation and its API."""

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from weather.model_spread import (
    MM_PER_INCH,
    agreement_level,
    summarize_spread,
)


def _hourly(day, high, low, precip_mm_per_hour=0.0, hours=24):
    """24 hourly rows for one day: the first hour is the high, the second the low."""
    times = [f"{day}T{hour:02d}:00" for hour in range(hours)]
    temps = [
        (high if h == 0 else low if h == 1 else (high + low) / 2) for h in range(hours)
    ]
    return {
        "time": times,
        "temperature_2m": temps,
        "precipitation": [precip_mm_per_hour] * hours,
    }


def _model(name, **days):
    hourly = {"time": [], "temperature_2m": [], "precipitation": []}
    for day, (high, low, rain) in days.items():
        part = _hourly(day[1:].replace("_", "-"), high, low, rain)
        for key in hourly:
            hourly[key] += part[key]
    return {"name": name, "data": {"hourly": hourly}, "error": None, "skipped": None}


def test_agreement_level_thresholds():
    assert agreement_level(3.0, (3.0, 6.0)) == "high"
    assert agreement_level(3.1, (3.0, 6.0)) == "moderate"
    assert agreement_level(6.0, (3.0, 6.0)) == "moderate"
    assert agreement_level(6.1, (3.0, 6.0)) == "low"


def test_models_that_agree_report_high_agreement():
    results = [
        _model("GFS", d2024_06_01=(80, 60, 0)),
        _model("ICON", d2024_06_01=(81, 61, 0)),
        _model("ECMWF", d2024_06_01=(79, 59, 0)),
    ]
    summary = summarize_spread(results)

    (day,) = summary["days"]
    assert day["date"] == "2024-06-01"
    assert day["high"] == {
        "min": 79.0,
        "median": 80.0,
        "max": 81.0,
        "spread": 2.0,
        "agreement": "high",
        "outlier": None,
        "models": 3,
    }
    assert day["precip"]["spread"] == 0
    assert day["agreement"] == "high"
    assert summary["models_used"] == ["ECMWF", "GFS", "ICON"]


def test_disagreement_names_the_outlier_and_takes_the_worst_variable():
    results = [
        _model("GFS", d2024_06_01=(80, 60, 0)),
        _model("ICON", d2024_06_01=(81, 60, 0)),
        _model("GEM", d2024_06_01=(92, 60, 0)),
    ]
    (day,) = summarize_spread(results)["days"]

    assert day["high"]["agreement"] == "low"
    assert day["high"]["outlier"] == "GEM"
    assert day["low"]["agreement"] == "high"
    assert day["agreement"] == "low"


def test_precipitation_is_totaled_per_day_in_inches():
    one_inch_per_day_mm = MM_PER_INCH / 24
    results = [
        _model("GFS", d2024_06_01=(80, 60, one_inch_per_day_mm)),
        _model("ICON", d2024_06_01=(80, 60, 0)),
    ]
    (day,) = summarize_spread(results)["days"]

    assert day["precip"]["max"] == pytest.approx(1.0, abs=0.01)
    assert day["precip"]["min"] == 0
    assert day["precip"]["agreement"] == "low"
    assert day["precip"]["outlier"] in {"GFS", "ICON"}


def test_partial_days_and_single_model_days_are_dropped():
    partial = {
        "name": "HRRR",
        "data": {"hourly": _hourly("2024-06-01", 90, 50, hours=10)},
        "error": None,
        "skipped": None,
    }
    results = [
        _model("GFS", d2024_06_01=(80, 60, 0), d2024_06_02=(70, 50, 0)),
        _model("ICON", d2024_06_01=(80, 60, 0)),
        partial,
    ]
    days = summarize_spread(results)["days"]

    assert [d["date"] for d in days] == ["2024-06-01"]  # 06-02 has only one model
    assert days[0]["models"] == 2  # the 10-hour HRRR day is excluded


def test_failed_and_skipped_models_are_reported_not_used():
    results = [
        _model("GFS", d2024_06_01=(80, 60, 0)),
        _model("ICON", d2024_06_01=(80, 60, 0)),
        {"name": "NAM", "data": None, "error": "Timeout", "skipped": None},
        {"name": "HRRR", "data": None, "error": None, "skipped": "Outside domain"},
        {"name": "GEM", "data": {"hourly": {}}, "error": None, "skipped": None},
    ]
    summary = summarize_spread(results)

    assert summary["models_failed"] == {"NAM": "Timeout", "GEM": "No data"}
    assert summary["models_skipped"] == ["HRRR"]
    assert summary["models_used"] == ["GFS", "ICON"]


def test_missing_precipitation_still_compares_temperatures():
    no_rain = _model("GFS", d2024_06_01=(80, 60, 0))
    del no_rain["data"]["hourly"]["precipitation"]
    results = [no_rain, _model("ICON", d2024_06_01=(80, 60, 0))]
    (day,) = summarize_spread(results)["days"]

    assert "precip" not in day
    assert day["high"]["models"] == 2


def test_no_comparable_days_returns_empty_list():
    assert summarize_spread([])["days"] == []
    assert summarize_spread([_model("GFS", d2024_06_01=(80, 60, 0))])["days"] == []


class TestModelSpreadAPI:
    URL = "/api/model-spread/"

    def _results(self, models):
        return [
            _model(name, d2024_06_01=(80 + i, 60, 0)) for i, name in enumerate(models)
        ]

    def test_returns_summary_for_requested_models(self):
        with patch(
            "weather.api.model_spread_api.ModelComparisonAPIView.fetch_all_models",
            side_effect=lambda models, *_a: self._results(models),
        ) as fetch:
            response = APIClient().get(
                self.URL,
                {"latitude": "35", "longitude": "-97", "models": "gfs, icon,bogus"},
            )

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["models_used"] == ["GFS", "ICON"]
        assert response.data["days"][0]["high"]["spread"] == 1.0
        assert fetch.call_args.args[0] == ["GFS", "ICON"]
        assert fetch.call_args.args[3] == 7

    def test_defaults_to_all_configured_models(self):
        with patch(
            "weather.api.model_spread_api.ModelComparisonAPIView.fetch_all_models",
            side_effect=lambda models, *_a: self._results(models),
        ) as fetch:
            response = APIClient().get(self.URL, {"latitude": "35", "longitude": "-97"})

        assert response.status_code == 200
        assert "GFS" in fetch.call_args.args[0]
        assert len(fetch.call_args.args[0]) >= 8

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"latitude": "x", "longitude": "1"},
            {"latitude": "95", "longitude": "1"},
            {"latitude": "35", "longitude": "-97", "forecast_days": "0"},
            {"latitude": "35", "longitude": "-97", "forecast_days": "17"},
            {"latitude": "35", "longitude": "-97", "forecast_days": "abc"},
        ],
    )
    def test_rejects_invalid_parameters(self, params):
        response = APIClient().get(self.URL, params)

        assert response.status_code == 400
        assert response.data["status"] == "error"
