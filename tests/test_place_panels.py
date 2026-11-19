"""Tests for the independently loadable place-page panels."""

from unittest.mock import patch

import pytest
import requests
from rest_framework.test import APIClient
from test_place import ALERTS, FORECAST, OBSERVATION, POINTS, STATIONS, _json_response

from weather import place_service

URL = "/api/place/{}/"
COORDS = {"latitude": "35.2", "longitude": "-97.4"}


def _nws_get(url, **_kwargs):
    routes = {
        "/points/": POINTS,
        "/stations/KOUN/": OBSERVATION,
        "nws.test/stations": STATIONS,
        "nws.test/forecast": FORECAST,
        "/alerts/active": ALERTS,
    }
    for fragment, payload in routes.items():
        if fragment in url:
            return _json_response(payload)
    raise AssertionError(f"unexpected URL {url}")


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


def _failing_get(status):
    def get(url, **_kwargs):
        raise _http_error(status)

    return get


def test_current_panel_returns_plain_data():
    with patch("requests.get", side_effect=_nws_get):
        data = place_service.fetch_current_panel(35.2, -97.4)

    assert data["office"] == "OUN"
    assert data["temperature"] == 68
    assert data["apparent_temperature"] == 71
    assert data["conditions"] == "Sunny"
    assert data["wind_direction"] == "E"
    assert data["observed_at"].startswith("2026-11-18T12:00:00")


def test_current_panel_without_stations_has_empty_readings():
    points = {"properties": {"gridId": "OUN"}}
    with patch("requests.get", return_value=_json_response(points)):
        data = place_service.fetch_current_panel(35.2, -97.4)

    assert data["office"] == "OUN"
    assert data["temperature"] is None
    assert data["observed_at"] is None


def test_forecast_panel_groups_periods_by_day():
    with patch("requests.get", side_effect=_nws_get):
        days = place_service.fetch_forecast_panel(35.2, -97.4)

    assert len(days) == 1
    assert days[0]["date"] == "2026-11-18"
    assert days[0]["day"]["wind_speed"] == 15
    assert days[0]["day"]["precipitation_probability"] == 10
    assert days[0]["night"]["short_forecast"] == "Clear"


def test_forecast_panel_handles_a_day_without_a_night_period():
    forecast = {"properties": {"periods": [FORECAST["properties"]["periods"][0]]}}

    def get(url, **kwargs):
        return (
            _json_response(forecast)
            if "nws.test/forecast" in url
            else _nws_get(url, **kwargs)
        )

    with patch("requests.get", side_effect=get):
        days = place_service.fetch_forecast_panel(35.2, -97.4)

    assert days[0]["night"] is None


def test_forecast_panel_without_forecast_url_is_empty():
    with patch("requests.get", return_value=_json_response({"properties": {}})):
        assert place_service.fetch_forecast_panel(35.2, -97.4) == []


def test_alerts_panel_serializes_alerts():
    with patch("requests.get", side_effect=_nws_get):
        alerts = place_service.fetch_alerts_panel(35.2, -97.4)

    assert [a["event"] for a in alerts] == ["Wind Advisory", "Unknown"]
    assert alerts[0]["severity"] == "moderate"
    assert alerts[0]["expires"].startswith("2026-11-19T00:00:00")
    assert alerts[1]["onset"] is None


class TestPlacePanelAPI:
    @pytest.mark.parametrize("panel", ["current", "forecast", "alerts"])
    def test_each_panel_returns_success(self, panel):
        with patch("requests.get", side_effect=_nws_get):
            response = APIClient().get(URL.format(panel), COORDS)

        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert response.data["supported"] is True
        assert response.data["data"]

    def test_unknown_panel_is_404(self):
        response = APIClient().get(URL.format("radar"), COORDS)

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "params",
        [{}, {"latitude": "x", "longitude": "1"}, {"latitude": "95", "longitude": "1"}],
    )
    def test_rejects_invalid_coordinates(self, params):
        response = APIClient().get(URL.format("current"), params)

        assert response.status_code == 400

    def test_place_outside_nws_coverage_is_reported_unsupported(self):
        with patch("requests.get", side_effect=_failing_get(404)):
            response = APIClient().get(URL.format("forecast"), COORDS)

        assert response.status_code == 404
        assert response.data["supported"] is False

    def test_upstream_server_error_is_a_502(self):
        with patch("requests.get", side_effect=_failing_get(500)):
            response = APIClient().get(URL.format("alerts"), COORDS)

        assert response.status_code == 502
        assert response.data["status"] == "error"

    def test_unexpected_failure_is_a_502(self):
        with patch("requests.get", side_effect=OSError("down")):
            response = APIClient().get(URL.format("current"), COORDS)

        assert response.status_code == 502

    def test_one_failing_panel_does_not_affect_another(self):
        def get(url, **kwargs):
            if "/alerts/" in url:
                raise _http_error(500)
            return _nws_get(url, **kwargs)

        client = APIClient()
        with patch("requests.get", side_effect=get):
            alerts = client.get(URL.format("alerts"), COORDS)
            forecast = client.get(URL.format("forecast"), COORDS)

        assert alerts.status_code == 502
        assert forecast.status_code == 200
