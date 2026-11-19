"""Tests for the on-demand historical climate analysis API."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from weather.api.climate_analysis_api import (
    ClimateAnalysisAPIView,
    ClimateAnalysisThrottle,
)
from weather.climate_data import ClimateDataError, IndexSeries, WeatherDay

URL = "/api/climate-analysis/"
PARAMS = {"lat": "30", "lon": "-97", "month": "1", "day": "1"}


class FakeDate(date):
    @classmethod
    def today(cls):
        return cls(2023, 1, 2)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def three_years(monkeypatch):
    """Pin the analysis to 2020-2022 with temperature rising alongside NAO."""
    monkeypatch.setattr(ClimateAnalysisAPIView, "first_year", 2019)
    monkeypatch.setattr("weather.api.climate_analysis_api.date", FakeDate)
    weather = {
        date(year, 1, 1) + timedelta(days=offset): WeatherDay(
            mean_temperature=float((year - 2019) * 10 + offset)
        )
        for year in range(2020, 2023)
        for offset in range(-3, 4)
    }
    nao = IndexSeries(
        "nao",
        "daily",
        "https://example.com/nao",
        {date(year, 1, 1): float(year - 2019) for year in range(2020, 2023)},
    )
    calls = {}

    def fake_weather(*args):
        calls["weather"] = args
        return weather

    monkeypatch.setattr(
        "weather.api.climate_analysis_api.fetch_weather_window", fake_weather
    )
    monkeypatch.setattr(
        "weather.api.climate_analysis_api.fetch_index_series_many",
        lambda _keys: ({"nao": nao}, {}),
    )
    return calls


def test_climate_analysis_returns_calendar_day_samples_and_correlation(three_years):
    response = APIClient().get(URL, {**PARAMS, "index": "nao"})

    assert response.status_code == 200
    assert len(response.data["weather"]) == 3
    assert response.data["calendar_day"] == "01-01"
    assert response.data["year_count"] == 3
    assert response.data["latitude"] == 30
    assert response.data["indexes_available"] is True
    assert response.data["unavailable_indices"] == []
    correlation = next(
        item
        for item in response.data["correlations"]
        if item["index"] == "nao" and item["weather_variable"] == "mean_temperature"
    )
    assert correlation["value"] == pytest.approx(1.0)
    assert correlation["sample_count"] == 3
    assert three_years["weather"][:2] == (30.0, -97.0)


def test_climate_analysis_reports_failed_indices_but_keeps_others(
    three_years, monkeypatch
):
    monkeypatch.setattr(
        "weather.api.climate_analysis_api.fetch_index_series_many",
        lambda _keys: (
            {
                "nao": IndexSeries(
                    "nao", "daily", "u", {date(2021, 1, 1): 1.0, date(2022, 1, 1): 2.0}
                )
            },
            {"ao": "boom"},
        ),
    )
    response = APIClient().get(URL, PARAMS)

    assert response.status_code == 200
    assert response.data["unavailable_indices"] == ["ao"]
    assert {item["index"] for item in response.data["indices"]} == {"nao"}


def test_climate_analysis_502_when_weather_unavailable(monkeypatch):
    def fail(*_args):
        raise ClimateDataError("down")

    monkeypatch.setattr("weather.api.climate_analysis_api.fetch_weather_window", fail)
    response = APIClient().get(URL, PARAMS)

    assert response.status_code == 502
    assert "weather" in response.data["error"]


def test_climate_analysis_502_when_every_index_unavailable(monkeypatch):
    monkeypatch.setattr(
        "weather.api.climate_analysis_api.fetch_weather_window",
        lambda *_args: {},
    )
    monkeypatch.setattr(
        "weather.api.climate_analysis_api.fetch_index_series_many",
        lambda _keys: ({}, {"nao": "down"}),
    )
    response = APIClient().get(URL, PARAMS)

    assert response.status_code == 502
    assert "index" in response.data["error"]


def test_climate_analysis_validates_parameters():
    client = APIClient()
    assert client.get(URL).status_code == 400
    assert client.get(URL, {**PARAMS, "lat": "abc"}).status_code == 400
    assert client.get(URL, {**PARAMS, "lat": "91"}).status_code == 400
    assert client.get(URL, {**PARAMS, "month": "13"}).status_code == 400
    assert client.get(URL, {**PARAMS, "day": "32"}).status_code == 400
    assert client.get(URL, {**PARAMS, "index": "bad"}).status_code == 400


def test_climate_analysis_throttles_anonymous_requests(monkeypatch, three_years):
    monkeypatch.setattr(ClimateAnalysisThrottle, "rate", "1/minute")
    client = APIClient()

    assert client.get(URL, PARAMS).status_code == 200
    assert client.get(URL, PARAMS).status_code == 429


def test_leap_day_skips_non_leap_years(three_years):
    response = APIClient().get(URL, {**PARAMS, "month": "2", "day": "29"})

    assert response.status_code == 200
    assert response.data["calendar_day"] == "02-29"


def test_climate_indices_endpoint_returns_latest_values(monkeypatch):
    monkeypatch.setattr(
        "weather.api.climate_analysis_api.latest_index_values",
        lambda: ([{"index": "nao", "value": 0.5}], ["ao"]),
    )
    response = APIClient().get("/api/climate-indices/")

    assert response.status_code == 200
    assert response.data == {
        "indices": [{"index": "nao", "value": 0.5}],
        "unavailable_indices": ["ao"],
    }


def test_climate_analysis_helpers_average_complete_windows_and_events():
    view = ClimateAnalysisAPIView()
    weekly = {}
    for year in range(2015, 2025):
        center = date(year, 6, 15)
        weather = {
            field: float(year - 2010 + offset)
            for offset, field in enumerate(view.weather_fields)
        }
        weekly[center] = {
            "date": center.isoformat(),
            "source_kind": "weekly_average",
            "source_identifier": "test",
            **weather,
        }
    rows = {
        center + timedelta(days=offset): SimpleNamespace(
            mean_temperature=80 + year,
            precipitation=0.1,
            wind_speed=5,
            snowfall=0,
        )
        for year, center in [(year, date(year, 6, 15)) for year in range(2015, 2025)]
        for offset in range(-3, 4)
    }
    averaged = view._weekly_weather(rows, range(2015, 2025), 6, 15)
    assert len(averaged) == 10
    indices = [
        {"index": "nao", "date": center.isoformat(), "value": float(index)}
        for index, center in enumerate(weekly)
    ]
    assert len(view._correlations(indices, weekly)) == 4
    events, thresholds = view._event_correlations(indices, weekly)
    assert len(events) == 4
    assert set(thresholds) == {"warm", "cool", "dry", "wet"}


def test_climate_analysis_serialization_helpers():
    view = ClimateAnalysisAPIView()
    assert view._serialize_weather({"date": "x"}) == {"date": "x"}
    assert view._weather_value(None, "mean_temperature") is None
    assert view._weather_value({"mean_temperature": 80}, "mean_temperature") == 80
    assert (
        view._weather_value(WeatherDay(mean_temperature=80), "mean_temperature") == 80
    )
    assert len(view._window_dates(date(2025, 6, 15))) == 7


def test_window_mean_indices_average_daily_and_monthly_series():
    view = ClimateAnalysisAPIView()
    daily = IndexSeries(
        "ao", "daily", "d", {date(2021, 6, 12 + i): float(i) for i in range(7)}
    )
    monthly = IndexSeries("oni", "monthly", "m", {(2021, 6): 0.4})
    empty = IndexSeries("pna", "daily", "p", {})

    results = view._window_mean_indices(
        {"ao": daily, "oni": monthly, "pna": empty}, [2021], 6, 15
    )

    by_index = {item["index"]: item for item in results}
    assert set(by_index) == {"ao", "oni"}
    assert by_index["ao"]["value"] == pytest.approx(3.0)
    assert by_index["ao"]["days_averaged"] == 7
    assert by_index["oni"]["cadence"] == "monthly"
    assert by_index["oni"]["value"] == pytest.approx(0.4)


def test_climate_analysis_flags_small_samples_and_multiple_testing(three_years):
    response = APIClient().get(URL, {**PARAMS, "index": "nao"})

    assert response.status_code == 200
    for item in response.data["correlations"]:
        assert item["warnings"] == ["too_few_samples"]  # only 3 years
    for item in response.data["event_correlations"]:
        assert "too_few_samples" in item["warnings"]
    assert response.data["multiple_testing"]["tests"] == 0  # no p-values with n=3
    assert "Only 3 completed years" in response.data["caveats"][0]


def test_climate_analysis_caveats_mention_monthly_indices(monkeypatch, three_years):
    oni = IndexSeries(
        "oni",
        "monthly",
        "https://example.com/oni",
        {(year, 1): float(year - 2019) for year in range(2020, 2023)},
    )
    monkeypatch.setattr(
        "weather.api.climate_analysis_api.fetch_index_series_many",
        lambda _keys: ({"oni": oni}, {}),
    )

    response = APIClient().get(URL, {**PARAMS, "index": "oni"})

    assert any("ONI is published monthly" in c for c in response.data["caveats"])
