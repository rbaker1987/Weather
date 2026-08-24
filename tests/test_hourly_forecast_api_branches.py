"""Tests for hourly forecast API edge cases and helper branches."""

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from django.test import Client

from weather.api.hourly_forecast_api import HourlyForecastForLocationAPIView


class Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


@pytest.mark.django_db
class TestHourlyForecastAPI:
    def test_requires_coordinates(self):
        response = Client().get("/api/hourly_forecast/")

        assert response.status_code == 400
        assert "lat and lon" in response.json()["error"]

    def test_returns_not_found_when_hourly_url_is_missing(self):
        with patch(
            "weather.api.hourly_forecast_api.requests.get",
            return_value=Response({"properties": {}}),
        ):
            response = Client().get("/api/hourly_forecast/?lat=30&lon=-97")

        assert response.status_code == 404
        assert response.json()["error"] == "Hourly forecast not available"

    def test_filters_by_date_and_formats_nws_period(self):
        periods = [
            {
                "startTime": "2026-08-24T12:00:00Z",
                "temperature": 80,
                "shortForecast": "Sunny",
                "windSpeed": "10 mph",
                "windDirection": "S",
                "windGust": "15 mph",
                "probabilityOfPrecipitation": {"value": "30"},
                "apparentTemperature": {"value": 26, "unitCode": "wmoUnit:degC"},
                "relativeHumidity": {"value": 50},
            },
            {
                "startTime": "2026-08-25T12:00:00Z",
                "temperature": 70,
                "shortForecast": "Rain",
                "windSpeed": "5 mph",
            },
        ]
        with (
            patch(
                "weather.api.hourly_forecast_api.requests.get",
                side_effect=[
                    Response({"properties": {"forecastHourly": "hourly-url"}}),
                    Response({"properties": {"periods": periods}}),
                ],
            ),
            patch.object(
                HourlyForecastForLocationAPIView,
                "_compute_sunrise_sunset",
                return_value=(
                    datetime(2026, 8, 24, 6, tzinfo=timezone.utc),
                    datetime(2026, 8, 24, 18, tzinfo=timezone.utc),
                ),
            ),
        ):
            response = Client().get(
                "/api/hourly_forecast/?lat=30&lon=-97&date=2026-08-24&hours=1"
            )

        assert response.status_code == 200
        payload = response.json()
        assert len(payload["hours"]) == 1
        assert payload["hours"][0]["apparentTemp"] == 78
        assert payload["hours"][0]["windGust"] == 15
        assert payload["hours"][0]["pop"] == 30
        assert list(payload["sun_events"]) == ["2026-08-24"]

    def test_request_failure_returns_server_error(self):
        import requests

        with patch(
            "weather.api.hourly_forecast_api.requests.get",
            side_effect=requests.RequestException("offline"),
        ):
            response = Client().get("/api/hourly_forecast/?lat=30&lon=-97")

        assert response.status_code == 500
        assert response.json()["error"] == "Failed to fetch forecast data"

    def test_weather_icon_mapping(self):
        view = HourlyForecastForLocationAPIView()
        expected = {
            "Thunderstorm": "bolt",
            "Freezing rain": "cloud-meatball",
            "Snow showers": "snowflake",
            "Fog": "smog",
            "Rain showers": "cloud-rain",
            "Windy": "wind",
            "Partly cloudy": "cloud-sun",
            "Clear": "sun",
            "Overcast": "cloud",
            "Unknown": "cloud-moon",
        }

        for condition, icon in expected.items():
            assert view._get_weather_icon(condition, condition != "Unknown") == icon

    def test_sunrise_sunset_fallback(self):
        view = HourlyForecastForLocationAPIView()
        with patch(
            "weather.api.hourly_forecast_api.sun",
            side_effect=RuntimeError("astral unavailable"),
        ):
            sunrise, sunset = view._compute_sunrise_sunset(date(2026, 8, 24), 30, -97)

        assert sunrise.hour == 6
        assert sunset.hour == 18
