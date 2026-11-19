"""Tests for forecast verification against station observations."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from weather import forecast_verification as fv

TODAY = date(2026, 11, 18)


def _obs(day, hour, celsius, offset_hours=0):
    """An NWS observation feature at a local ``hour`` on ``day``."""
    stamp = f"{day.isoformat()}T{(hour - offset_hours) % 24:02d}:00:00+00:00"
    return {
        "properties": {
            "timestamp": stamp,
            "temperature": {"unitCode": "wmoUnit:degC", "value": celsius},
        }
    }


def _day_obs(day, high_c, low_c, hours=24):
    return [
        _obs(
            day,
            hour,
            high_c if hour == 15 else low_c if hour == 5 else (high_c + low_c) / 2,
        )
        for hour in range(hours)
    ]


def _hourly(model_id, lead, per_day):
    """Hourly arrays for ``per_day = {date: (high_f, low_f)}`` (24 values per day)."""
    times, values = [], []
    for day, (high, low) in per_day.items():
        for hour in range(24):
            times.append(f"{day.isoformat()}T{hour:02d}:00")
            values.append(
                high if hour == 15 else low if hour == 5 else (high + low) / 2
            )
    return {"time": times, f"temperature_2m_previous_day{lead}_{model_id}": values}


def test_observed_daily_extremes_converts_to_fahrenheit_and_local_days():
    day = date(2026, 11, 15)
    features = _day_obs(day, 20, 10)  # 68 F high, 50 F low
    features.append({"properties": {"timestamp": "bad", "temperature": {"value": 1}}})
    features.append({"properties": {"timestamp": None, "temperature": {"value": 1}}})
    features.append(
        {
            "properties": {
                "timestamp": "2026-11-15T01:00:00Z",
                "temperature": {"value": None},
            }
        }
    )

    result = fv.observed_daily_extremes(features, 0)

    assert result == {day: (pytest.approx(68.0), pytest.approx(50.0))}


def test_observed_daily_extremes_respects_utc_offset_and_minimum_coverage():
    day = date(2026, 11, 15)
    # 24 hourly obs starting 06:00Z are the local day 00:00-23:00 at UTC-6.
    features = [
        {
            "properties": {
                "timestamp": f"2026-11-15T{h:02d}:00:00+00:00"
                if h >= 6
                else f"2026-11-16T{h:02d}:00:00+00:00",
                "temperature": {"value": 10 + (h % 5)},
            }
        }
        for h in range(24)
    ]
    sparse = _day_obs(date(2026, 11, 14), 20, 10, hours=5)

    result = fv.observed_daily_extremes(features + sparse, -6 * 3600)

    assert set(result) == {day}
    assert fv.observed_daily_extremes(sparse, 0) == {}


def test_forecast_daily_extremes_requires_nearly_full_days():
    full = date(2026, 11, 15)
    hourly = _hourly("gfs_seamless", 1, {full: (70.0, 50.0)})
    hourly["time"].append("2026-11-16T00:00")
    hourly["temperature_2m_previous_day1_gfs_seamless"].append(90.0)  # 1 hour only

    result = fv.forecast_daily_extremes(hourly, "gfs_seamless", 1)

    assert result == {full: (70.0, 50.0)}
    assert fv.forecast_daily_extremes(hourly, "icon_seamless", 1) == {}
    assert fv.forecast_daily_extremes({}, "gfs_seamless", 1) == {}


def test_forecast_daily_extremes_skips_missing_values():
    hourly = _hourly("gfs_seamless", 1, {date(2026, 11, 15): (70.0, 50.0)})
    hourly["temperature_2m_previous_day1_gfs_seamless"][3] = None
    hourly["temperature_2m_previous_day1_gfs_seamless"][4] = None
    hourly["temperature_2m_previous_day1_gfs_seamless"][5] = None
    hourly["temperature_2m_previous_day1_gfs_seamless"][6] = None
    hourly["temperature_2m_previous_day1_gfs_seamless"][7] = None

    assert fv.forecast_daily_extremes(hourly, "gfs_seamless", 1) == {}


def test_score_forecasts_computes_mae_and_bias_over_completed_days_only():
    d1, d2, d3 = date(2026, 11, 15), date(2026, 11, 16), TODAY
    observed = {d1: (70.0, 50.0), d2: (60.0, 40.0), d3: (80.0, 60.0)}
    forecast = {d1: (72.0, 49.0), d2: (57.0, 40.0), d3: (99.0, 99.0)}

    score = fv.score_forecasts(forecast, observed, TODAY)

    assert score == {
        "days": 2,
        "high_mae": 2.5,
        "low_mae": 0.5,
        "high_bias": -0.5,
        "low_bias": -0.5,
    }


def test_score_forecasts_returns_none_without_overlap():
    assert fv.score_forecasts({}, {date(2026, 11, 15): (1.0, 0.0)}, TODAY) is None
    assert (
        fv.score_forecasts(
            {date(2026, 11, 15): (1.0, 0.0)}, {date(2026, 11, 14): (1.0, 0.0)}, TODAY
        )
        is None
    )


def _scenario():
    days = [TODAY - timedelta(days=n) for n in range(1, 5)]
    observed_features = []
    for day in days:
        observed_features += _day_obs(day, 20, 10)  # 68 / 50 F

    def runs_for(model_id, high_error_1, high_error_3):
        hourly = {}
        for lead, error in ((1, high_error_1), (3, high_error_3)):
            part = _hourly(model_id, lead, dict.fromkeys(days, (68.0 + error, 50.0)))
            hourly.setdefault("time", part["time"])
            hourly.update({k: v for k, v in part.items() if k != "time"})
        return hourly

    hourly = {}
    for model_id, e1, e3 in (("gfs_seamless", 1.0, 5.0), ("icon_seamless", 3.0, 2.0)):
        for key, value in runs_for(model_id, e1, e3).items():
            hourly[key] = value
    return {"hourly": hourly, "utc_offset_seconds": 0}, observed_features


def test_verify_models_ranks_models_per_lead_time():
    runs, features = _scenario()
    with (
        patch.object(fv, "_fetch_previous_runs", return_value=runs),
        patch.object(
            fv,
            "_fetch_observations",
            return_value=({"id": "KOUN", "name": "Norman"}, features),
        ),
    ):
        result = fv.verify_models(35.2, -97.4, ["GFS", "ICON", "bogus"], today=TODAY)

    assert result["station"] == {"id": "KOUN", "name": "Norman"}
    assert result["leads"] == [1, 3]
    by_name = {m["name"]: m["scores"] for m in result["models"]}
    assert by_name["GFS"]["1"]["high_mae"] == 1.0
    assert by_name["ICON"]["3"]["high_mae"] == 2.0
    assert by_name["GFS"]["1"]["days"] == 4
    assert result["best"]["1"] == {"high": "GFS", "low": "GFS"}
    assert result["best"]["3"]["high"] == "ICON"


def test_verify_models_omits_models_without_scores_and_best_needs_two():
    runs, features = _scenario()
    with (
        patch.object(fv, "_fetch_previous_runs", return_value=runs),
        patch.object(
            fv, "_fetch_observations", return_value=({"id": "K", "name": "K"}, features)
        ),
    ):
        result = fv.verify_models(35.2, -97.4, ["GFS", "HRRR"], today=TODAY)

    assert [m["name"] for m in result["models"]] == ["GFS"]  # HRRR has no data
    assert result["best"] == {}


def test_verify_models_wraps_unexpected_fetch_errors():
    with (
        patch.object(fv, "_fetch_previous_runs", side_effect=OSError("down")),
        patch.object(
            fv, "_fetch_observations", return_value=({"id": "K", "name": "K"}, [])
        ),
        pytest.raises(fv.VerificationError, match="Could not fetch"),
    ):
        fv.verify_models(35.2, -97.4, today=TODAY)


def test_verify_models_passes_through_missing_station():
    with (
        patch.object(fv, "_fetch_previous_runs", return_value={"hourly": {}}),
        patch.object(
            fv,
            "_fetch_observations",
            side_effect=fv.VerificationError("No observation stations"),
        ),
        pytest.raises(fv.VerificationError, match="No observation stations"),
    ):
        fv.verify_models(35.2, -97.4, today=TODAY)


def _points():
    return {
        "properties": {
            "observationStations": "https://api.weather.gov/gridpoints/x/stations"
        }
    }


def test_nearest_station_uses_first_station_with_identifier():
    stations = {
        "features": [
            {"properties": {}},
            {"properties": {"stationIdentifier": "KOUN", "name": "Norman"}},
        ]
    }

    def fake(url, ttl=0):
        return _points() if "/points/" in url else stations

    with patch.object(fv, "_get_json", side_effect=fake):
        assert fv._nearest_station(35.2, -97.4) == {"id": "KOUN", "name": "Norman"}


def test_nearest_station_errors_when_none_available():
    with (
        patch.object(fv, "_get_json", return_value={"properties": {}}),
        pytest.raises(fv.VerificationError),
    ):
        fv._nearest_station(35.2, -97.4)

    def fake(url, ttl=0):
        return _points() if "/points/" in url else {"features": []}

    with (
        patch.object(fv, "_get_json", side_effect=fake),
        pytest.raises(fv.VerificationError),
    ):
        fv._nearest_station(35.2, -97.4)


def test_fetch_observations_requests_a_day_stable_window():
    urls = []

    def fake(url, ttl=0):
        urls.append(url)
        return {"features": [{"properties": {}}]}

    with (
        patch.object(fv, "_nearest_station", return_value={"id": "KOUN", "name": "N"}),
        patch.object(fv, "_get_json", side_effect=fake),
    ):
        station, features = fv._fetch_observations(35.2, -97.4, TODAY)

    assert station["id"] == "KOUN"
    assert features == [{"properties": {}}]
    assert "start=2026-11-10T00:00:00Z" in urls[0]
    assert "stations/KOUN/observations" in urls[0]


def test_fetch_previous_runs_builds_request_and_caches():
    payload = {"hourly": {}}
    with patch.object(fv, "get_json", return_value=payload) as get:
        assert fv._fetch_previous_runs(35.2, -97.4, ["GFS", "ECMWF"]) == payload

    params = get.call_args.kwargs["params"]
    assert params["models"] == "gfs_seamless,ecmwf_ifs025"
    assert (
        params["hourly"] == "temperature_2m_previous_day1,temperature_2m_previous_day3"
    )
    assert get.call_args.kwargs["ttl"] == fv.FORECAST_CACHE_SECONDS


class TestForecastVerificationAPI:
    URL = "/api/forecast-verification/"

    def test_returns_scores(self):
        result = {"station": {"id": "K", "name": "K"}, "models": [], "best": {}}
        with patch(
            "weather.api.forecast_verification_api.verify_models", return_value=result
        ) as verify:
            response = APIClient().get(
                self.URL, {"latitude": "35", "longitude": "-97", "models": "gfs, icon"}
            )

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["station"] == {"id": "K", "name": "K"}
        assert verify.call_args.args == (35.0, -97.0, ["GFS", "ICON"])

    def test_defaults_to_all_models(self):
        with patch(
            "weather.api.forecast_verification_api.verify_models", return_value={}
        ) as verify:
            APIClient().get(self.URL, {"latitude": "35", "longitude": "-97"})

        assert verify.call_args.args[2] is None

    def test_upstream_failure_is_a_502(self):
        with patch(
            "weather.api.forecast_verification_api.verify_models",
            side_effect=fv.VerificationError("No observation stations near this place"),
        ):
            response = APIClient().get(self.URL, {"latitude": "35", "longitude": "-97"})

        assert response.status_code == 502
        assert "unavailable" in response.data["error"]
        assert "stations" not in response.data["error"]

    @pytest.mark.parametrize(
        "params",
        [{}, {"latitude": "x", "longitude": "1"}, {"latitude": "95", "longitude": "1"}],
    )
    def test_rejects_invalid_coordinates(self, params):
        response = APIClient().get(self.URL, params)

        assert response.status_code == 400
