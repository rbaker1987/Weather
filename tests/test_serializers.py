"""Tests for serializers."""

import pytest
from decimal import Decimal
from datetime import date, datetime
from django.utils import timezone

from weather.models import Location, DailyForecast
from weather.serializers import LocationSerializer, DailyForecastSerializer


@pytest.mark.django_db
class TestLocationSerializer:
    """Test Location serializer."""

    def test_serialize_location(self):
        """Test serializing a location instance."""
        location = Location.objects.create(
            name="Austin, TX",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431"),
            current_temp=75,
            current_conditions="Sunny"
        )

        serializer = LocationSerializer(location)
        data = serializer.data

        assert data['name'] == "Austin, TX"
        assert float(data['latitude']) == pytest.approx(30.2672, rel=1e-4)
        assert float(data['longitude']) == pytest.approx(-97.7431, rel=1e-4)
        # Serializer does not expose current conditions fields
        assert 'current_temp' not in data
        assert 'current_conditions' not in data

    def test_deserialize_location(self):
        """Test deserializing location data."""
        data = {
            'name': 'Dallas, TX',
            'latitude': 32.7767,
            'longitude': -96.7970,
        }

        serializer = LocationSerializer(data=data)
        assert serializer.is_valid()

        location = serializer.save()
        assert location.name == "Dallas, TX"
        assert float(location.latitude) == pytest.approx(32.7767, rel=1e-4)
        assert float(location.longitude) == pytest.approx(-96.7970, rel=1e-4)

    def test_location_validation_invalid_latitude(self):
        """Test location validation rejects invalid latitude."""
        data = {
            'name': 'Invalid',
            'latitude': 100.0,  # Invalid: > 90
            'longitude': -96.7970,
        }

        serializer = LocationSerializer(data=data)
        assert not serializer.is_valid()
        assert 'latitude' in serializer.errors

    def test_location_validation_invalid_longitude(self):
        """Test location validation rejects invalid longitude."""
        data = {
            'name': 'Invalid',
            'latitude': 32.7767,
            'longitude': 200.0,  # Invalid: > 180
        }

        serializer = LocationSerializer(data=data)
        assert not serializer.is_valid()
        assert 'longitude' in serializer.errors


@pytest.mark.django_db
class TestDailyForecastSerializer:
    """Test DailyForecast serializer."""

    def test_serialize_daily_forecast(self):
        """Test serializing a daily forecast."""
        location = Location.objects.create(
            name="Austin, TX",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431")
        )

        forecast = DailyForecast.objects.create(
            location=location,
            forecast_date=date(2025, 11, 20),
            period_start=timezone.now(),
            period_end=timezone.now(),
            temperature=75,
            high_temperature=80,
            low_temperature=60,
            short_forecast="Partly Cloudy",
            detailed_forecast="Partly cloudy with a high near 80.",
            wind_speed=5,
        )

        serializer = DailyForecastSerializer(forecast)
        data = serializer.data

        assert data['forecast_date'] == "2025-11-20"
        assert data['high_temperature'] == 80
        assert data['low_temperature'] == 60
        assert data['short_forecast'] == "Partly Cloudy"

    def test_deserialize_daily_forecast(self):
        """Test deserializing daily forecast data."""
        location = Location.objects.create(
            name="Austin, TX",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431")
        )

        data = {
            'location': location.id,
            'forecast_date': '2025-11-21',
            'period_start': timezone.now().isoformat(),
            'period_end': timezone.now().isoformat(),
            'temperature': 70,
            'high_temperature': 85,
            'low_temperature': 65,
            'short_forecast': 'Sunny',
            'wind_speed': 5,
        }

        serializer = DailyForecastSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

        forecast = serializer.save()
        assert forecast.forecast_date == date(2025, 11, 21)
        assert forecast.high_temperature == 85
        assert forecast.low_temperature == 65
        assert forecast.short_forecast == "Sunny"

    def test_forecast_validation_missing_required_fields(self):
        """Test forecast validation catches missing required fields."""
        data = {
            'forecast_date': '2025-11-21',
            # Missing location, temps, and forecast
        }

        serializer = DailyForecastSerializer(data=data)
        assert not serializer.is_valid()
        assert 'location' in serializer.errors
