"""Tests for the ENSO-based seasonal analog outlook."""

from datetime import date, timedelta
from unittest.mock import Mock, patch

import pytest
from rest_framework.test import APIClient

from weather import seasonal_outlook as so
from weather.climate_data import ClimateDataError, IndexSeries

TODAY = date(2026, 11, 19)


def _oni(latest_month=(2026, 9), per_year=lambda year: float(year - 1990) / 10):
    """ONI values for the latest month of every year, plus this year's."""
    values = {(year, latest_month[1]): per_year(year) for year in range(1950, 2026)}
    values[latest_month] = 2.0
    return IndexSeries("oni", "monthly", "https://example.com/oni", values)


def _monthly(temp=lambda _year, _month: 50.0, rain=lambda _year, _month: 2.0):
    return {
        (year, month): {
            "temperature": temp(year, month),
            "precipitation": rain(year, month),
        }
        for year in range(1950, 2027)
        for month in range(1, 13)
    }


@pytest.mark.parametrize(
    ("value", "phase"),
    [
        (2.4, "El Niño"),
        (0.5, "El Niño"),
        (0.49, "Neutral"),
        (-0.49, "Neutral"),
        (-0.5, "La Niña"),
    ],
)
def test_enso_phase(value, phase):
    assert so.enso_phase(value) == phase


def test_aggregate_monthly_averages_temperature_and_totals_precipitation():
    days = [date(2024, 2, 1) + timedelta(days=n) for n in range(29)]
    daily = {
        "time": [d.isoformat() for d in days],
        "temperature_2m_mean": [40.0 + (n % 2) * 10 for n in range(29)],
        "precipitation_sum": [0.1] * 29,
    }

    monthly = so.aggregate_monthly(daily)

    assert monthly[(2024, 2)]["temperature"] == pytest.approx((40 * 15 + 50 * 14) / 29)
    assert monthly[(2024, 2)]["precipitation"] == pytest.approx(2.9)


def test_aggregate_monthly_skips_sparse_months_and_bad_rows():
    daily = {
        "time": ["bad", "2024-03-01", "2024-03-02"],
        "temperature_2m_mean": [1.0, 2.0, None],
        "precipitation_sum": [0.0, 0.0, 0.0],
    }

    assert so.aggregate_monthly(daily) == {}
    assert so.aggregate_monthly({}) == {}


def test_following_months_roll_into_the_next_year():
    assert so._following_months(2026, 9) == [(2026, 10), (2026, 11), (2026, 12)]
    assert so._following_months(2026, 11) == [(2026, 12), (2027, 1), (2027, 2)]
    assert so._following_months(2026, 12) == [(2027, 1), (2027, 2), (2027, 3)]


def test_outlook_picks_the_years_closest_to_the_current_enso_state():
    # ONI per year runs from -4.0 (1950) up to 3.5 (2025); today's value is 2.0.
    oni = _oni()
    monthly = _monthly(
        temp=lambda year, _month: 60.0 if year >= 2020 else 50.0,
    )

    result = so.build_outlook(oni, monthly, TODAY)

    assert result["enso"] == {"value": 2.0, "phase": "El Niño", "as_of": "2026-09-01"}
    assert result["target_months"] == ["October", "November", "December"]
    years = [a["year"] for a in result["analog_years"]]
    assert len(years) == so.ANALOG_COUNT
    assert 2010 in years and 1950 not in years
    assert result["pool_years"] == 76
    assert result["climatology"]["temperature"] == pytest.approx(
        (50 * 70 + 60 * 6) / 76
    )
    assert result["anomaly"]["temperature"] == pytest.approx(
        result["analog_mean"]["temperature"] - result["climatology"]["temperature"]
    )
    assert result["agreement"]["count"] == so.ANALOG_COUNT
    assert result["agreement"]["wetter"] == 0  # identical precipitation everywhere


def test_outlook_counts_how_many_analogs_were_warmer_and_wetter():
    oni = _oni()
    # Analog years (the 8 nearest to +2.0) get warm/wet outcomes; others are cooler/drier.
    near = {a for a in range(2005, 2025) if abs((a - 1990) / 10 - 2.0) <= 0.45}
    monthly = _monthly(
        temp=lambda year, _month: 70.0 if year in near else 50.0,
        rain=lambda year, _month: 4.0 if year in near else 1.0,
    )

    result = so.build_outlook(oni, monthly, TODAY)

    assert result["agreement"]["warmer"] == len(
        near & {a["year"] for a in result["analog_years"]}
    )
    assert result["anomaly"]["temperature"] > 0
    assert result["anomaly"]["precipitation"] > 0


def test_outlook_always_labels_itself_as_low_skill_and_notes_stale_enso():
    result = so.build_outlook(_oni(), _monthly(), TODAY)

    assert "low skill" in result["caveats"][0]
    assert any("September 2026" in c for c in result["caveats"])  # two months old


def test_outlook_omits_the_stale_note_when_enso_is_current():
    oni = _oni(latest_month=(2026, 10))

    result = so.build_outlook(oni, _monthly(), TODAY)

    assert not any("may already be over" in c for c in result["caveats"])


def test_outlook_skips_years_without_complete_following_months():
    monthly = _monthly()
    for year in range(1950, 1990):
        del monthly[(year, 10)]

    result = so.build_outlook(_oni(), monthly, TODAY)

    assert result["pool_years"] == 36


def test_outlook_requires_enough_history():
    monthly = {key: value for key, value in _monthly().items() if key[0] >= 2010}

    with pytest.raises(so.OutlookError, match="Not enough history"):
        so.build_outlook(_oni(), monthly, TODAY)


def test_outlook_requires_a_published_enso_value():
    empty = IndexSeries("oni", "monthly", "u", {})

    with pytest.raises(so.OutlookError, match="No published ENSO"):
        so.build_outlook(empty, _monthly(), TODAY)


def test_fetch_monthly_weather_requests_history_once_and_caches():
    days = [date(2024, 3, 1) + timedelta(days=n) for n in range(31)]
    payload = Mock()
    payload.json.return_value = {
        "daily": {
            "time": [d.isoformat() for d in days],
            "temperature_2m_mean": [55.0] * 31,
            "precipitation_sum": [0.05] * 31,
        }
    }
    payload.raise_for_status.return_value = None
    with patch("requests.get", return_value=payload) as get:
        first = so.fetch_monthly_weather(35.21, -97.44)
        second = so.fetch_monthly_weather(35.24, -97.41)

    assert first == second
    assert get.call_count == 1
    assert get.call_args.kwargs["params"]["start_date"] == "1950-01-01"
    assert first[(2024, 3)]["precipitation"] == pytest.approx(1.55)


def test_fetch_monthly_weather_errors_when_nothing_usable():
    payload = Mock()
    payload.json.return_value = {"daily": {}}
    payload.raise_for_status.return_value = None
    with (
        patch("requests.get", return_value=payload),
        pytest.raises(ClimateDataError, match="no monthly data"),
    ):
        so.fetch_monthly_weather(35.2, -97.4)


def test_fetch_monthly_weather_rejects_non_json():
    payload = Mock()
    payload.json.side_effect = ValueError("bad")
    payload.raise_for_status.return_value = None
    with (
        patch("requests.get", return_value=payload),
        pytest.raises(ClimateDataError, match="not JSON"),
    ):
        so.fetch_monthly_weather(35.2, -97.4)


class TestSeasonalOutlookAPI:
    URL = "/api/seasonal-outlook/"
    PARAMS = {"lat": "35.2", "lon": "-97.4"}

    def _patch(self, **overrides):
        targets = {
            "fetch_index_series": _oni(),
            "fetch_monthly_weather": _monthly(),
        }
        targets.update(overrides)
        return [
            patch(
                f"weather.api.seasonal_outlook_api.{name}",
                **(
                    {"side_effect": value}
                    if isinstance(value, Exception)
                    else {"return_value": value}
                ),
            )
            for name, value in targets.items()
        ]

    def test_returns_the_outlook(self):
        patches = self._patch()
        with (
            patches[0],
            patches[1],
            patch("weather.api.seasonal_outlook_api.date") as fake_date,
        ):
            fake_date.today.return_value = TODAY
            response = APIClient().get(self.URL, self.PARAMS)

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["enso"]["phase"] == "El Niño"
        assert "low skill" in response.data["caveats"][0]

    @pytest.mark.parametrize(
        "params", [{}, {"lat": "x", "lon": "1"}, {"lat": "95", "lon": "1"}]
    )
    def test_rejects_invalid_coordinates(self, params):
        assert APIClient().get(self.URL, params).status_code == 400

    @pytest.mark.parametrize(
        "failure",
        [ClimateDataError("down"), so.OutlookError("thin")],
    )
    def test_data_failures_are_a_502(self, failure):
        patches = self._patch(fetch_monthly_weather=failure)
        with patches[0], patches[1]:
            response = APIClient().get(self.URL, self.PARAMS)

        assert response.status_code == 502
        assert response.data["status"] == "error"

    def test_has_its_own_throttle_bucket(self):
        from weather.api.climate_analysis_api import ClimateAnalysisThrottle
        from weather.api.seasonal_outlook_api import SeasonalOutlookThrottle

        assert SeasonalOutlookThrottle.scope != ClimateAnalysisThrottle.scope
