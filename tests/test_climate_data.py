"""Tests for on-demand climate data fetching and parsing."""

from datetime import date, timedelta

import pytest
import requests
from django.core.cache import cache

from weather import climate_data
from weather.climate_data import (
    ClimateDataError,
    IndexSeries,
    fetch_index_series,
    fetch_index_series_many,
    fetch_weather_window,
    latest_index_values,
    parse_daily,
    parse_monthly,
    standardize,
)

MONTHLY_TEXT = "2024 1 2 3 4 5 6 7 8 9 10 11 12\n"


class Response:
    def __init__(self, text="", payload=None, error=None):
        self.text = text
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def down():
    return Response(error=requests.ConnectionError("down"))


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_parse_daily_skips_bad_and_missing_rows():
    text = (
        "year,month,day,value\n2024,1,1,1.5\n2024 1 2 -99.9\n2024,1,3,x\n2024,2,30,1\n"
    )
    assert parse_daily(text) == {date(2024, 1, 1): 1.5}


def test_parse_monthly_reads_twelve_columns():
    text = "1950 2099\n2020 1.0 2.0 3 4 5 6 7 8 9 10 11 -99.9\n2020 1 2 3 4 5 6 7 8 9 10 11 x\nabc 1 2\n"
    values = parse_monthly(text)
    assert values[(2020, 1)] == 1.0
    assert (2020, 12) not in values
    assert len(values) == 11


def test_standardize_scales_by_calendar_month_baseline():
    values = {date(1991 + i, 1, 1): float(i) for i in range(30)}
    values[date(2024, 1, 1)] = 100.0
    values[date(1991, 2, 1)] = 5.0  # a single value has zero deviation
    z = standardize(values)
    assert z[date(1991, 1, 1)] < 0 < z[date(2020, 1, 1)]
    assert date(1991, 2, 1) not in z
    assert z[date(2024, 1, 1)] > 5


def test_index_series_lookup_and_latest():
    daily = IndexSeries(
        "nao", "daily", "u", {date(2024, 1, 1): 1.0, date(2024, 1, 5): 2.0}
    )
    assert daily.value_on(date(2024, 1, 5)) == 2.0
    assert daily.value_on(date(2024, 1, 2)) is None
    assert daily.latest(date(2024, 1, 4)) == (date(2024, 1, 1), 1.0)
    assert daily.latest(date(2023, 1, 1)) is None

    monthly = IndexSeries("oni", "monthly", "u", {(2024, 1): 0.5, (2024, 3): 0.7})
    assert monthly.value_on(date(2024, 3, 20)) == 0.7
    assert monthly.latest(date(2024, 2, 10)) == (date(2024, 1, 1), 0.5)
    assert monthly.latest(date(2023, 12, 31)) is None


def test_fetch_index_series_downloads_once_and_caches(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return Response("2024,1,1,0.25\n")

    monkeypatch.setattr(climate_data.requests, "get", fake_get)
    first = fetch_index_series("nao")
    second = fetch_index_series("nao")

    assert first.cadence == "daily"
    assert first.values == {date(2024, 1, 1): 0.25}
    assert second == first
    assert len(calls) == 1


def test_standardized_daily_index(monkeypatch):
    text = "".join(f"{1991 + i},1,1,{i}\n" for i in range(30))
    monkeypatch.setattr(climate_data.requests, "get", lambda *_a, **_k: Response(text))
    series = fetch_index_series("epo")
    assert series.cadence == "daily"
    assert series.values[date(2005, 1, 1)] == pytest.approx(0.0, abs=0.1)


def test_daily_failure_falls_back_to_monthly(monkeypatch):
    def fake_get(url, **kwargs):
        if url == climate_data.DAILY_INDEX_URLS["nao"]:
            return down()
        return Response(MONTHLY_TEXT)

    monkeypatch.setattr(climate_data.requests, "get", fake_get)
    series = fetch_index_series("nao")
    assert series.cadence == "monthly"
    assert series.values[(2024, 12)] == 12.0


def test_empty_daily_file_falls_back_to_monthly(monkeypatch):
    def fake_get(url, **kwargs):
        if url == climate_data.DAILY_INDEX_URLS["ao"]:
            return Response("nothing useful")
        return Response(MONTHLY_TEXT)

    monkeypatch.setattr(climate_data.requests, "get", fake_get)
    assert fetch_index_series("ao").cadence == "monthly"


def test_daily_only_index_failure_raises(monkeypatch):
    monkeypatch.setattr(climate_data.requests, "get", lambda *_a, **_k: down())
    with pytest.raises(ClimateDataError):
        fetch_index_series("wpo")


def test_monthly_only_index_without_values_raises(monkeypatch):
    monkeypatch.setattr(
        climate_data.requests, "get", lambda *_a, **_k: Response("junk")
    )
    with pytest.raises(ClimateDataError):
        fetch_index_series("oni")


def test_unknown_index_has_no_source():
    with pytest.raises(ClimateDataError):
        climate_data._download_index("nope")


def test_fetch_many_collects_errors_and_series(monkeypatch):
    def fake_get(url, **kwargs):
        if "oni" in url:
            return down()
        return Response("2024,1,1,1.0\n")

    monkeypatch.setattr(climate_data.requests, "get", fake_get)
    series, errors = fetch_index_series_many(["nao", "oni", "nao"])
    assert set(series) == {"nao"}
    assert set(errors) == {"oni"}


def test_latest_index_values_lists_found_indices(monkeypatch):
    series = {
        "nao": IndexSeries("nao", "daily", "u", {date(2024, 1, 1): 1.0}),
        "oni": IndexSeries("oni", "monthly", "m", {(2030, 1): 1.0}),
    }
    monkeypatch.setattr(
        climate_data, "fetch_index_series_many", lambda _keys: (series, {"ao": "x"})
    )
    latest, unavailable = latest_index_values(date(2024, 6, 1))
    assert latest == [
        {
            "index": "nao",
            "date": "2024-01-01",
            "value": 1.0,
            "cadence": "daily",
            "source_url": "u",
        }
    ]
    assert unavailable == ["ao"]


def _archive_payload(first_year, last_year):
    days = (date(last_year + 1, 1, 7) - date(first_year, 1, 1)).days + 1
    dates = [date(first_year, 1, 1) + timedelta(days=i) for i in range(days)]
    return {
        "daily": {
            "time": [d.isoformat() for d in dates] + ["bad-date"],
            "temperature_2m_mean": [float(d.year) for d in dates],
            "precipitation_sum": [0.1] * len(dates),
            "wind_speed_10m_max": [None] * len(dates),
            "snowfall_sum": [],
        }
    }


def test_fetch_weather_window_keeps_only_window_dates_and_caches(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(kwargs["params"])
        return Response(payload=_archive_payload(2020, 2021))

    monkeypatch.setattr(climate_data.requests, "get", fake_get)
    result = fetch_weather_window(30.1234, -97.5, 2, 29, 2020, 2021)

    assert set(result) == {date(2020, 2, 29) + timedelta(days=o) for o in range(-3, 4)}
    day = result[date(2020, 2, 29)]
    assert day.mean_temperature == 2020.0
    assert day.precipitation == 0.1
    assert day.wind_speed is None
    assert day.snowfall is None
    assert calls[0]["latitude"] == 30.1234
    assert calls[0]["timezone"] == "auto"
    assert fetch_weather_window(30.1234, -97.5, 2, 29, 2020, 2021) == result
    assert len(calls) == 1


def test_fetch_weather_window_errors(monkeypatch):
    monkeypatch.setattr(
        climate_data.requests,
        "get",
        lambda *_a, **_k: Response(error=requests.Timeout("slow")),
    )
    with pytest.raises(ClimateDataError):
        fetch_weather_window(30, -97, 1, 1, 2020, 2021)

    monkeypatch.setattr(climate_data.requests, "get", lambda *_a, **_k: Response())
    with pytest.raises(ClimateDataError, match="JSON"):
        fetch_weather_window(30, -97, 1, 1, 2020, 2021)

    monkeypatch.setattr(
        climate_data.requests, "get", lambda *_a, **_k: Response(payload={"daily": {}})
    )
    with pytest.raises(ClimateDataError, match="no daily data"):
        fetch_weather_window(30, -97, 1, 1, 2020, 2021)
