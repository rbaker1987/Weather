"""Tests for custom hourly forecast merging and edge handling."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.test import Client

from weather.api.hourly_forecast_api import _TZ_CACHE
from weather.models import HourlyForecast, Location


class Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


@pytest.mark.django_db
def test_custom_hourly_forecast_overrides_nws_data():
    latitude = 30.123
    longitude = -97.456
    location = Location.objects.create(
        name="Austin", latitude=latitude, longitude=longitude
    )
    start = datetime.now(timezone.utc).replace(minute=15, second=0, microsecond=0)
    HourlyForecast.objects.create(
        location=location,
        forecast_date=start.date(),
        period_start=start,
        period_end=start + timedelta(hours=1),
        temperature=88,
        apparent_temperature=90,
        short_forecast="Custom skies",
        wind_speed=12,
        wind_direction="S",
        wind_gust=20,
        precipitation_probability=40,
    )
    _TZ_CACHE.clear()
    responses = [
        Response({"properties": {"forecastHourly": "hourly-url"}}),
        Response(
            {
                "properties": {
                    "periods": [
                        {
                            "startTime": start.isoformat().replace("+00:00", "Z"),
                            "temperature": 70,
                            "shortForecast": "NWS skies",
                            "windSpeed": "5 mph",
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
        finder.return_value.timezone_at.return_value = "UTC"
        response = Client().get(
            f"/api/hourly_forecast/?lat={latitude}&lon={longitude}&hours=1"
        )

    assert response.status_code == 200
    hour = response.json()["hours"][0]
    assert hour["temp"] == 88
    assert hour["condition"] == "Custom skies"
    assert hour["wind"] == "12 mph"
    assert hour["pop"] == 40


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
