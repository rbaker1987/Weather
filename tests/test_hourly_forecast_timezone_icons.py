"""Tests for custom hourly forecast merging and edge handling."""

from unittest.mock import patch

import pytest
from django.test import Client

from weather.api.hourly_forecast_api import _TZ_CACHE


class Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


@pytest.mark.django_db
def test_hourly_forecast_uses_utc_when_timezone_lookup_fails():
    _TZ_CACHE.clear()
    responses = [
        Response({"properties": {"forecastHourly": "hourly-url"}}),
        Response(
            {
                "properties": {
                    "periods": [
                        {
                            "startTime": "2026-08-24T12:00:00Z",
                            "temperature": 70,
                            "shortForecast": "Clear",
                        }
                    ]
                }
            }
        ),
    ]

    with (
        patch("weather.api.hourly_forecast_api.requests.get", side_effect=responses),
        patch("weather.api.hourly_forecast_api.TimezoneFinder") as finder,
    ):
        finder.return_value.timezone_at.side_effect = RuntimeError("lookup failed")
        response = Client().get("/api/hourly_forecast/?lat=30&lon=-97&hours=1")

    assert response.status_code == 200
    assert response.json()["timezone"] == "UTC"


def test_hourly_forecast_icon_handles_all_condition_families():
    from weather.api.hourly_forecast_api import HourlyForecastForLocationAPIView

    view = HourlyForecastForLocationAPIView()
    assert view._get_weather_icon("Mostly cloudy", False) == "cloud"
    assert view._get_weather_icon("Unknown", True) == "cloud-sun"
