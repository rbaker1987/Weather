"""Serializer tests for Location, BulkForecastRequest, and WeatherAlert."""

from datetime import timedelta

import pytest
from django.utils import timezone

from weather.models import (
    CurrentConditions,
    DailyForecast,
    ForecastRequest,
    HourlyForecast,
    Location,
    WeatherAlert,
)
from weather.serializers import (
    BulkForecastRequestSerializer,
    CurrentConditionsSerializer,
    DailyForecastSerializer,
    ForecastRequestSerializer,
    HourlyForecastSerializer,
    LocationCreateSerializer,
    LocationSerializer,
    WeatherAlertSerializer,
)


@pytest.mark.django_db
class TestSerializers:
    def test_location_serializer_valid(self):
        data = {
            "name": "SerializerTest",
            "latitude": "40.7128",
            "longitude": "-74.0060",
            "zip_code": "10001",
        }
        serializer = LocationSerializer(data=data)
        assert serializer.is_valid()
        location = serializer.save()
        assert location.name == "SerializerTest"

    def test_location_serializer_missing_name(self):
        data = {"latitude": "40.0", "longitude": "-74.0"}
        serializer = LocationSerializer(data=data)
        assert not serializer.is_valid()
        assert "name" in serializer.errors

    def test_bulk_forecast_serializer_valid(self):
        data = {
            "locations": ["Austin", "Dallas"],
            "forecast_type": "daily",
            "days": 5,
            "include_alerts": True,
        }
        serializer = BulkForecastRequestSerializer(data=data)
        assert serializer.is_valid()

    def test_bulk_forecast_serializer_invalid_type(self):
        data = {
            "locations": ["Austin"],
            "forecast_type": "invalid",
            "days": 3,
            "include_alerts": False,
        }
        serializer = BulkForecastRequestSerializer(data=data)
        assert not serializer.is_valid()

    def test_weather_alert_serializer(self):
        loc = Location.objects.create(name="AlertTest")
        alert = WeatherAlert.objects.create(
            location=loc,
            nws_alert_id="TEST123",
            event="Severe Thunderstorm Warning",
            headline="Dangerous Storm",
            description="Take shelter immediately",
            severity=WeatherAlert.Severity.SEVERE,
            urgency=WeatherAlert.Urgency.IMMEDIATE,
            expires=timezone.now() + timedelta(hours=2),
        )
        serializer = WeatherAlertSerializer(alert)
        data = serializer.data
        assert data["event"] == "Severe Thunderstorm Warning"
        assert data["severity"] == "severe"

    def test_location_serializer_display_name_and_forecast_count(self):
        loc = Location.objects.create(name="Default", custom_name="Favorite")
        serializer = LocationSerializer(loc)

        assert serializer.data["display_name"] == "Favorite"
        assert serializer.data["forecast_count"] == 0

    @pytest.mark.parametrize(
        "payload",
        [
            {"latitude": 40.0, "longitude": -74.0},
            {"zip_code": "10001"},
            {"address": "1 Main Street"},
            {"name": "Austin"},
        ],
    )
    def test_location_create_serializer_accepts_supported_inputs(self, payload):
        serializer = LocationCreateSerializer(data=payload)

        assert serializer.is_valid()

    def test_location_create_serializer_requires_input(self):
        serializer = LocationCreateSerializer(data={})

        assert not serializer.is_valid()
        assert "Must provide" in str(serializer.errors)

    def test_current_conditions_serializer_computed_fields(self):
        loc = Location.objects.create(name="Current")
        current = CurrentConditions.objects.create(
            location=loc,
            temperature=72,
            condition="Sunny",
            wind_speed=5,
            humidity=50,
            last_observation_time=timezone.now(),
        )
        CurrentConditions.objects.filter(pk=current.pk).update(
            updated_at=timezone.now() - timedelta(minutes=20)
        )
        current.refresh_from_db()

        data = CurrentConditionsSerializer(current).data

        assert data["location_name"] == "Current"
        assert data["location_id"] == str(loc.id)
        assert data["is_stale"] is True
        assert data["age_minutes"] >= 20

    def test_hourly_and_daily_forecast_serializer_fields(self):
        loc = Location.objects.create(name="Forecast")
        now = timezone.now()
        hourly = HourlyForecast.objects.create(
            location=loc,
            forecast_date=now.date(),
            period_start=now,
            period_end=now + timedelta(hours=1),
            temperature=65,
            apparent_temperature=62,
            temperature_unit="F",
            short_forecast="Cloudy",
            wind_speed=4,
        )
        daily = DailyForecast.objects.create(
            location=loc,
            forecast_date=now.date(),
            period_start=now,
            period_end=now + timedelta(hours=12),
            temperature=70,
            high_temperature=75,
            low_temperature=55,
            temperature_unit="F",
            short_forecast="Sunny",
            wind_speed=4,
        )

        hourly_data = HourlyForecastSerializer(hourly).data
        daily_data = DailyForecastSerializer(daily).data

        assert hourly_data["apparent_temperature_display"] == "62°F"
        assert hourly_data["location_name"] == "Forecast"
        assert daily_data["temperature_range"] == "55°F - 75°F"
        assert daily_data["location_name"] == "Forecast"

    def test_weather_alert_expiry_fields(self):
        loc = Location.objects.create(name="Alert")
        alert = WeatherAlert.objects.create(
            location=loc,
            event="Watch",
            expires=timezone.now() + timedelta(hours=2),
        )

        data = WeatherAlertSerializer(alert).data

        assert data["is_expired"] is False
        assert data["time_until_expiry"] in {"1 hours", "2 hours"}

    def test_forecast_request_serializer_includes_user_and_locations(self):
        first = Location.objects.create(name="First")
        second = Location.objects.create(name="Second")
        request = ForecastRequest.objects.create(
            session_key="forecast-user-session", request_type="daily"
        )
        request.locations_requested.set([first, second])

        data = ForecastRequestSerializer(request).data

        assert data["user_name"] == "forecast-user-session"
        assert data["location_names"] == ["First", "Second"]

    def test_bulk_forecast_serializer_rejects_empty_locations(self):
        serializer = BulkForecastRequestSerializer(data={"locations": []})

        assert not serializer.is_valid()
