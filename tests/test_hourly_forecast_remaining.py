"""Tests for remaining hourly forecast API branches."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone as django_timezone

from weather.api.hourly_forecast_api import _TZ_CACHE, HourlyForecastForLocationAPIView
from weather.models import HourlyForecast, Location


class Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


@pytest.mark.django_db
def test_hourly_api_calculates_apparent_temperature_when_missing():
    _TZ_CACHE.clear()
    periods = [
        {
            "startTime": "2026-08-25T12:00:00Z",
            "temperature": 30,
            "relativeHumidity": {"value": 80},
            "windSpeed": "15 mph",
            "shortForecast": "Cold",
        }
    ]
    with (
        patch(
            "weather.api.hourly_forecast_api.requests.get",
            side_effect=[
                Response({"properties": {"forecastHourly": "hourly-url"}}),
                Response({"properties": {"periods": periods}}),
            ],
        ),
        patch("weather.api.hourly_forecast_api.TimezoneFinder") as finder,
        patch(
            "weather.api.hourly_forecast_api.calculate_apparent_temperature",
            return_value=20,
        ) as apparent,
    ):
        finder.return_value.timezone_at.return_value = "UTC"
        response = Client().get("/api/hourly_forecast/?lat=30&lon=-97&hours=1")

    assert response.status_code == 200
    assert response.json()["hours"][0]["apparentTemp"] == 20
    apparent.assert_called_once_with(temperature_f=30, humidity=80, wind_speed_mph=15)


@pytest.mark.django_db
def test_hourly_api_handles_malformed_period_without_aborting_response():
    _TZ_CACHE.clear()
    periods = [
        {"startTime": "not-a-date"},
        {
            "startTime": "2026-08-25T12:00:00Z",
            "temperature": 70,
            "shortForecast": "Clear",
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
        patch("weather.api.hourly_forecast_api.TimezoneFinder") as finder,
    ):
        finder.return_value.timezone_at.return_value = "UTC"
        response = Client().get("/api/hourly_forecast/?lat=30&lon=-97&hours=2")

    assert response.status_code == 500
    assert "Invalid isoformat" in response.json()["error"]


@pytest.mark.django_db
def test_hourly_api_uses_closest_custom_forecast_for_rounded_hour():
    _TZ_CACHE.clear()
    location = Location.objects.create(name="Austin", latitude=30, longitude=-97)
    start = django_timezone.now().replace(minute=0, second=0, microsecond=0)
    HourlyForecast.objects.create(
        location=location,
        forecast_date=start.date(),
        period_start=start + timedelta(minutes=40),
        period_end=start + timedelta(hours=1),
        temperature=81,
        apparent_temperature=80,
        short_forecast="Near",
        wind_speed=5,
        nws_data_url="",
    )
    with (
        patch(
            "weather.api.hourly_forecast_api.requests.get",
            side_effect=[
                Response({"properties": {"forecastHourly": "hourly-url"}}),
                Response(
                    {
                        "properties": {
                            "periods": [
                                {
                                    "startTime": start.isoformat().replace("+00:00", "Z"),
                                    "temperature": 70,
                                    "shortForecast": "NWS",
                                }
                            ]
                        }
                    }
                ),
            ],
        ),
        patch("weather.api.hourly_forecast_api.TimezoneFinder") as finder,
    ):
        finder.return_value.timezone_at.return_value = "UTC"
        response = Client().get("/api/hourly_forecast/?lat=30&lon=-97&hours=1")

    assert response.status_code == 200
    assert response.json()["hours"][0]["temp"] == 81


def test_hourly_api_sunrise_fallback_returns_fixed_utc_times():
    view = HourlyForecastForLocationAPIView()
    with patch("weather.api.hourly_forecast_api.sun", side_effect=ValueError("bad")):
        sunrise, sunset = view._compute_sunrise_sunset(
            datetime(2026, 8, 25).date(), 30, -97
        )

    assert sunrise == datetime(2026, 8, 25, 6, tzinfo=timezone.utc)
    assert sunset == datetime(2026, 8, 25, 18, tzinfo=timezone.utc)
