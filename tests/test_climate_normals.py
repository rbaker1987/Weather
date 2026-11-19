"""Tests for 1991-2020 climate normals computed from the Open-Meteo Archive."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from weather import climate_normals as cn


def _daily(first=1991, last=2020, high=70.0, low=50.0, precip=0.1, high_for=None):
    """An archive ``daily`` block with the same values every day (or ``high_for``)."""
    times, highs, lows, rain = [], [], [], []
    day = date(first, 1, 1)
    while day <= date(last, 12, 31):
        times.append(day.isoformat())
        highs.append(high_for(day) if high_for else high)
        lows.append(low)
        rain.append(precip)
        day += timedelta(days=1)
    return {
        "time": times,
        "temperature_2m_max": highs,
        "temperature_2m_min": lows,
        "precipitation_sum": rain,
    }


def test_constant_data_gives_constant_normals_for_every_calendar_day():
    normals = cn.compute_daily_normals(_daily())

    assert len(normals) == 366  # includes Feb 29, filled in from its neighbors
    assert normals[(2, 29)]["temperature_2m_max"] == pytest.approx(70.0)
    assert normals[(7, 4)]["temperature_2m_min"] == pytest.approx(50.0)
    assert normals[(12, 31)]["precipitation_sum"] == pytest.approx(0.1)


def test_normals_average_across_years_and_smooth_over_the_window():
    # Highs are 60 on Jan 10 and 70 on every other day, in every year.
    normals = cn.compute_daily_normals(
        _daily(high_for=lambda d: 60.0 if (d.month, d.day) == (1, 10) else 70.0)
    )

    assert normals[(1, 10)]["temperature_2m_max"] == pytest.approx((60 + 6 * 70) / 7)
    assert normals[(1, 13)]["temperature_2m_max"] == pytest.approx(
        (60 + 6 * 70) / 7
    )  # still inside the +/-3 day window
    assert normals[(1, 14)]["temperature_2m_max"] == pytest.approx(70.0)


def test_window_wraps_across_the_new_year():
    normals = cn.compute_daily_normals(
        _daily(high_for=lambda d: 40.0 if (d.month, d.day) == (1, 1) else 70.0)
    )

    assert normals[(12, 30)]["temperature_2m_max"] == pytest.approx((40 + 6 * 70) / 7)


def test_years_outside_the_baseline_are_ignored():
    daily = _daily(
        1989, 2022, high_for=lambda d: 99.0 if d.year in (1990, 2021) else 70.0
    )

    normals = cn.compute_daily_normals(daily)

    assert normals[(6, 1)]["temperature_2m_max"] == pytest.approx(70.0)


def test_days_without_enough_years_are_skipped():
    normals = cn.compute_daily_normals(_daily(1991, 2005))  # only 15 years

    assert normals == {}


def test_missing_values_and_bad_dates_are_tolerated():
    daily = _daily()
    daily["time"][0] = "not-a-date"  # Jan 1, 1991 is skipped
    daily["temperature_2m_max"][1] = None  # Jan 2, 1991 has no high

    normals = cn.compute_daily_normals(daily)

    assert normals[(1, 1)]["temperature_2m_max"] == pytest.approx(70.0)
    assert normals[(1, 2)]["temperature_2m_max"] == pytest.approx(70.0)


def test_a_short_column_leaves_too_few_years_to_compute_normals():
    daily = _daily()
    daily["precipitation_sum"] = daily["precipitation_sum"][:100]

    assert cn.compute_daily_normals(daily) == {}


def test_empty_block_gives_no_normals():
    assert cn.compute_daily_normals({}) == {}


def test_normals_for_dates_rounds_and_follows_the_calendar():
    normals = cn.compute_daily_normals(_daily(precip=0.123))

    rows = cn.normals_for_dates(normals, date(2026, 2, 27), 3)

    assert [r["date"] for r in rows] == ["2026-02-27", "2026-02-28", "2026-03-01"]
    assert rows[0] == {
        "date": "2026-02-27",
        "high": 70.0,
        "low": 50.0,
        "precipitation": 0.12,
    }


def test_normals_for_dates_skips_days_without_normals():
    assert cn.normals_for_dates({}, date(2026, 2, 27), 3) == []


def test_normals_for_dates_keeps_none_for_missing_fields():
    normals = {
        (2, 27): {
            "temperature_2m_max": None,
            "temperature_2m_min": 1.0,
            "precipitation_sum": None,
        }
    }

    rows = cn.normals_for_dates(normals, date(2026, 2, 27), 1)

    assert rows[0]["high"] is None
    assert rows[0]["precipitation"] is None


def test_fetch_requests_the_baseline_once_and_caches_by_rounded_coordinates():
    with patch.object(cn, "get_json", return_value={"daily": _daily()}) as get:
        first = cn.fetch_daily_normals(35.2123, -97.4456)
        second = cn.fetch_daily_normals(35.24, -97.41)  # rounds to the same place

    assert first == second
    assert get.call_count == 1
    params = get.call_args.kwargs["params"]
    assert (params["latitude"], params["longitude"]) == (35.2, -97.4)
    assert params["start_date"] == "1991-01-01"
    assert params["end_date"] == "2020-12-31"


def test_fetch_wraps_upstream_failures():
    with (
        patch.object(cn, "get_json", side_effect=OSError("down")),
        pytest.raises(cn.ClimateNormalsError, match="request failed"),
    ):
        cn.fetch_daily_normals(35.2, -97.4)


def test_fetch_rejects_a_response_without_usable_data():
    with (
        patch.object(cn, "get_json", return_value={"daily": {}}),
        pytest.raises(cn.ClimateNormalsError, match="no usable data"),
    ):
        cn.fetch_daily_normals(35.2, -97.4)


class TestClimateNormalsAPI:
    URL = "/api/climate-normals/"

    def _normals(self):
        return cn.compute_daily_normals(_daily())

    def test_returns_average_high_and_low_with_provenance(self):
        with patch(
            "weather.api.climate_normals_api.fetch_daily_normals",
            return_value=self._normals(),
        ):
            response = APIClient().get(self.URL, {"lat": "35.2", "lon": "-97.4"})

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["period"] == "1991-2020"
        assert "ERA5" in response.data["source"]
        assert response.data["avg_high_temp"] == 70.0
        assert response.data["avg_low_temp"] == 50.0
        assert len(response.data["daily"]) == 7

    def test_days_parameter_controls_the_window(self):
        with patch(
            "weather.api.climate_normals_api.fetch_daily_normals",
            return_value=self._normals(),
        ):
            response = APIClient().get(
                self.URL, {"lat": "35.2", "lon": "-97.4", "days": "3"}
            )

        assert len(response.data["daily"]) == 3

    def test_averages_are_none_when_no_days_have_normals(self):
        with patch(
            "weather.api.climate_normals_api.fetch_daily_normals", return_value={}
        ):
            response = APIClient().get(self.URL, {"lat": "35.2", "lon": "-97.4"})

        assert response.status_code == 200
        assert response.data["avg_high_temp"] is None
        assert response.data["avg_low_temp"] is None

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"lat": "x", "lon": "1"},
            {"lat": "95", "lon": "1"},
            {"lat": "30"},
            {"lat": "30", "lon": "-97", "days": "x"},
            {"lat": "30", "lon": "-97", "days": "0"},
            {"lat": "30", "lon": "-97", "days": "99"},
        ],
    )
    def test_rejects_invalid_parameters(self, params):
        response = APIClient().get(self.URL, params)

        assert response.status_code == 400

    def test_upstream_failure_is_a_502(self):
        with patch(
            "weather.api.climate_normals_api.fetch_daily_normals",
            side_effect=cn.ClimateNormalsError("down"),
        ):
            response = APIClient().get(self.URL, {"lat": "35.2", "lon": "-97.4"})

        assert response.status_code == 502
        assert response.data["status"] == "error"


def test_normals_and_analysis_throttles_do_not_share_a_bucket():
    from weather.api.climate_analysis_api import ClimateAnalysisThrottle
    from weather.api.climate_normals_api import ClimateNormalsThrottle

    assert ClimateNormalsThrottle.scope != ClimateAnalysisThrottle.scope
