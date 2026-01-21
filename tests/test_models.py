"""Tests for Django weather models."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from weather.models import (
    DailyForecast,
    ForecastRequest,
    HourlyForecast,
    Location,
    WeatherAlert,
)


@pytest.mark.django_db
class TestLocation:
    """Test the Location model."""

    def test_location_creation(self):
        """Test basic location creation."""
        location = Location.objects.create(
            name="Austin, TX",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431"),
        )

        assert location.name == "Austin, TX"
        assert location.latitude == Decimal("30.2672")
        assert location.longitude == Decimal("-97.7431")
        assert location.id is not None

    def test_location_custom_name(self):
        """Test location custom name."""
        location = Location.objects.create(
            name="Austin, TX",
            custom_name="Home",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431"),
        )

        assert location.display_name == "Home"

    def test_location_display_name_fallback(self):
        """Test location display name falls back to name."""
        location = Location.objects.create(
            name="Austin, TX",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431"),
        )

        assert location.display_name == "Austin, TX"

    def test_location_update_coordinates(self):
        """Test updating location coordinates."""
        location = Location.objects.create(
            name="Test Location", latitude=Decimal("30.0"), longitude=Decimal("-97.0")
        )
        location.update_coordinates(Decimal("31.0"), Decimal("-98.0"))
        assert location.latitude == Decimal("31.0")
        assert location.longitude == Decimal("-98.0")

    def test_location_set_as_favorite(self):
        """Test setting location as favorite."""
        loc1 = Location.objects.create(name="Location 1", is_favorite=True)
        loc2 = Location.objects.create(name="Location 2")

        loc2.set_as_favorite()
        loc1.refresh_from_db()

        assert loc2.is_favorite is True
        assert loc1.is_favorite is False

    def test_location_type_choices(self):
        """Test location type choices."""
        location = Location.objects.create(
            name="Home Office", location_type=Location.LocationType.HOME
        )
        assert location.location_type == "home"

    def test_location_ordering(self):
        """Test default ordering by current location flag."""
        Location.objects.create(
            name="A", is_current_location=False, display_order=0
        )
        loc2 = Location.objects.create(
            name="B", is_current_location=True, display_order=1
        )

        locations = list(Location.objects.all())
        assert locations[0].id == loc2.id  # Current location first


@pytest.mark.django_db
class TestDailyForecast:
    """Test the DailyForecast model."""

    def test_daily_forecast_creation(self):
        """Test basic daily forecast creation."""
        location = Location.objects.create(name="Test City")
        forecast = DailyForecast.objects.create(
            location=location,
            forecast_date=datetime.now().date(),
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(hours=12),
            temperature=75,
            high_temperature=80,
            low_temperature=65,
            short_forecast="Sunny",
            wind_speed=10,
            wind_direction="N",
        )

        assert forecast.location.name == "Test City"
        assert forecast.temperature == 75
        assert forecast.high_temperature == 80
        assert forecast.low_temperature == 65

    def test_daily_forecast_apparent_temperature_auto_set(self):
        """Test apparent temperature is auto-calculated on save."""
        location = Location.objects.create(name="Test City")
        forecast = DailyForecast.objects.create(
            location=location,
            forecast_date=datetime.now().date(),
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(hours=12),
            temperature=75,
            short_forecast="Sunny",
            wind_speed=10,
        )

        assert forecast.apparent_temperature == 75

    def test_daily_forecast_str_representation(self):
        """Test string representation."""
        location = Location.objects.create(name="Test City")
        forecast = DailyForecast.objects.create(
            location=location,
            forecast_date=datetime.now().date(),
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(hours=12),
            temperature=75,
            short_forecast="Partly Cloudy",
            wind_speed=10,
        )

        assert "Test City" in str(forecast)
        assert "Partly Cloudy" in str(forecast)


@pytest.mark.django_db
class TestHourlyForecast:
    """Test the HourlyForecast model."""

    def test_hourly_forecast_creation(self):
        """Test basic hourly forecast creation."""
        location = Location.objects.create(name="Test City")
        forecast = HourlyForecast.objects.create(
            location=location,
            forecast_date=datetime.now().date(),
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(hours=1),
            temperature=72,
            short_forecast="Clear",
            wind_speed=5,
            humidity=45,
            dew_point=55,
        )

        assert forecast.humidity == 45
        assert forecast.dew_point == 55
        assert forecast.temperature == 72

    def test_hourly_forecast_humidity_validation(self):
        """Test humidity stays within valid range."""
        location = Location.objects.create(name="Test City")
        forecast = HourlyForecast.objects.create(
            location=location,
            forecast_date=datetime.now().date(),
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(hours=1),
            temperature=72,
            short_forecast="Clear",
            wind_speed=5,
            humidity=100,
        )

        assert forecast.humidity == 100


@pytest.mark.django_db
class TestWeatherAlert:
    """Test the WeatherAlert model."""

    def test_weather_alert_creation(self):
        """Test basic alert creation."""
        location = Location.objects.create(name="Test City")
        alert = WeatherAlert.objects.create(
            location=location,
            nws_alert_id="TEST123",
            event="Severe Thunderstorm Warning",
            headline="Severe weather expected",
            description="Take shelter immediately",
            severity=WeatherAlert.Severity.SEVERE,
            urgency=WeatherAlert.Urgency.IMMEDIATE,
            onset=timezone.now(),
            expires=timezone.now() + timedelta(hours=2),
            is_active=True,
        )

        assert alert.event == "Severe Thunderstorm Warning"
        assert alert.severity == "severe"
        assert alert.urgency == "immediate"
        assert alert.is_active is True

    def test_weather_alert_is_expired_property(self):
        """Test is_expired property."""
        location = Location.objects.create(name="Test City")

        # Expired alert
        expired_alert = WeatherAlert.objects.create(
            location=location,
            nws_alert_id="EXP123",
            event="Test",
            headline="Test",
            description="Test",
            severity=WeatherAlert.Severity.MINOR,
            urgency=WeatherAlert.Urgency.PAST,
            expires=timezone.now() - timedelta(hours=1),
        )

        # Active alert
        active_alert = WeatherAlert.objects.create(
            location=location,
            nws_alert_id="ACT123",
            event="Test",
            headline="Test",
            description="Test",
            severity=WeatherAlert.Severity.MINOR,
            urgency=WeatherAlert.Urgency.EXPECTED,
            expires=timezone.now() + timedelta(hours=1),
        )

        assert expired_alert.is_expired is True
        assert active_alert.is_expired is False

    def test_weather_alert_no_expiry(self):
        """Test alert with no expiration date."""
        location = Location.objects.create(name="Test City")
        alert = WeatherAlert.objects.create(
            location=location,
            nws_alert_id="NOEXP123",
            event="Test",
            headline="Test",
            description="Test",
            severity=WeatherAlert.Severity.MODERATE,
            urgency=WeatherAlert.Urgency.EXPECTED,
        )

        assert alert.is_expired is False

    def test_weather_alert_str_representation(self):
        """Test string representation."""
        location = Location.objects.create(name="Dallas, TX")
        alert = WeatherAlert.objects.create(
            location=location,
            nws_alert_id="STR123",
            event="Heat Advisory",
            headline="Test",
            description="Test",
            severity=WeatherAlert.Severity.MODERATE,
            urgency=WeatherAlert.Urgency.EXPECTED,
        )

        assert "Heat Advisory" in str(alert)
        assert "Dallas, TX" in str(alert)


@pytest.mark.django_db
class TestForecastRequest:
    """Test the ForecastRequest model."""

    def test_forecast_request_creation(self):
        """Test basic request creation."""
        request = ForecastRequest.objects.create(
            session_key="test_session_123",
            request_type="forecast",
            status=ForecastRequest.RequestStatus.SUCCESS,
            response_time_ms=150,
            cache_hit=False,
        )

        assert request.session_key == "test_session_123"
        assert request.status == "success"
        assert request.response_time_ms == 150
        assert request.cache_hit is False

    def test_forecast_request_with_locations(self):
        """Test request with multiple locations."""
        loc1 = Location.objects.create(name="City 1")
        loc2 = Location.objects.create(name="City 2")

        request = ForecastRequest.objects.create(
            session_key="test_session",
            request_type="bulk_forecast",
            status=ForecastRequest.RequestStatus.SUCCESS,
        )
        request.locations_requested.add(loc1, loc2)

        assert request.locations_requested.count() == 2
        assert loc1 in request.locations_requested.all()

    def test_forecast_request_error_tracking(self):
        """Test error tracking."""
        request = ForecastRequest.objects.create(
            session_key="test_session",
            request_type="forecast",
            status=ForecastRequest.RequestStatus.FAILED,
            error_message="API timeout",
        )

        assert request.status == "failed"
        assert "timeout" in request.error_message

    def test_forecast_request_str_representation(self):
        """Test string representation."""
        request = ForecastRequest.objects.create(
            session_key="abcd1234567890",
            request_type="forecast",
            status=ForecastRequest.RequestStatus.SUCCESS,
        )

        string_repr = str(request)
        assert "abcd1234" in string_repr  # First 8 chars of session key
