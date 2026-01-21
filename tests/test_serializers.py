"""Serializer tests for Location, BulkForecastRequest, and WeatherAlert."""

from datetime import timedelta

import pytest
from django.utils import timezone

from weather.models import Location, WeatherAlert
from weather.serializers import (
    BulkForecastRequestSerializer,
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
