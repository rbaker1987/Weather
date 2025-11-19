"""Tests for Django admin interface."""

from datetime import datetime, time
from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.utils import timezone

from weather.admin import (
    DailyForecastAdmin,
    HourlyForecastAdmin,
    LocationAdmin,
    WeatherAlertAdmin,
)
from weather.models import DailyForecast, HourlyForecast, Location, WeatherAlert


@pytest.fixture
def admin_user(db):
    """Create an admin user."""
    return User.objects.create_superuser(username="admin", email="admin@test.com", password="admin123")


@pytest.fixture
def request_factory():
    """Request factory fixture."""
    return RequestFactory()


@pytest.fixture
def mock_request(request_factory, admin_user):
    """Create a mock request with admin user."""
    request = request_factory.get("/admin/")
    request.user = admin_user
    return request


@pytest.mark.django_db
class TestLocationAdmin:
    """Test LocationAdmin."""

    def test_coordinates_display_with_coords(self):
        """Test coordinates display when coordinates exist."""
        location = Location.objects.create(
            name="Test Location",
            latitude=Decimal("45.5231"),
            longitude=Decimal("-122.6765")
        )
        admin = LocationAdmin(Location, AdminSite())
        result = admin.coordinates_display(location)
        assert "45.5231" in result
        assert "-122.6765" in result

    def test_coordinates_display_without_coords(self):
        """Test coordinates display when no coordinates."""
        location = Location.objects.create(name="Test Location")
        admin = LocationAdmin(Location, AdminSite())
        result = admin.coordinates_display(location)
        assert result == "No coordinates"

    def test_forecast_count_with_forecasts(self):
        """Test forecast count display with existing forecasts."""
        location = Location.objects.create(name="Test Location")
        today = timezone.now().date()
        DailyForecast.objects.create(
            location=location,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=75,
            short_forecast="Sunny",
            wind_speed=10,
        )

        admin = LocationAdmin(Location, AdminSite())
        result = admin.forecast_count(location)
        assert "1 forecasts" in result
        assert "href" in result  # Check it's a link

    def test_forecast_count_without_forecasts(self):
        """Test forecast count display with no forecasts."""
        location = Location.objects.create(name="Test Location")
        admin = LocationAdmin(Location, AdminSite())
        result = admin.forecast_count(location)
        assert result == "0 forecasts"

    def test_last_update_with_date(self):
        """Test last update display with date."""
        location = Location.objects.create(
            name="Test Location",
            last_forecast_update=timezone.make_aware(datetime(2025, 11, 19, 14, 30))
        )
        admin = LocationAdmin(Location, AdminSite())
        result = admin.last_update(location)
        assert "2025-11-19" in result
        assert "14:30" in result

    def test_last_update_never(self):
        """Test last update display with no date."""
        location = Location.objects.create(name="Test Location")
        admin = LocationAdmin(Location, AdminSite())
        result = admin.last_update(location)
        assert result == "Never"

    def test_update_forecasts_action(self, mock_request):
        """Test update forecasts admin action."""
        location = Location.objects.create(name="Test Location")
        admin = LocationAdmin(Location, AdminSite())
        queryset = Location.objects.filter(pk=location.pk)

        admin.update_forecasts(mock_request, queryset)

        location.refresh_from_db()
        assert location.last_forecast_update is not None

    def test_deactivate_locations_action(self, mock_request):
        """Test deactivate locations admin action."""
        location = Location.objects.create(name="Test Location", is_active=True)
        admin = LocationAdmin(Location, AdminSite())
        queryset = Location.objects.filter(pk=location.pk)

        admin.deactivate_locations(mock_request, queryset)

        location.refresh_from_db()
        assert location.is_active is False


@pytest.mark.django_db
class TestDailyForecastAdmin:
    """Test DailyForecastAdmin."""

    def test_location_name_display(self):
        """Test location name display."""
        location = Location.objects.create(name="Portland")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=location,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=75,
            short_forecast="Sunny",
            wind_speed=10,
        )

        admin = DailyForecastAdmin(DailyForecast, AdminSite())
        result = admin.location_name(forecast)
        assert result == "Portland"

    def test_temperature_display(self):
        """Test temperature display."""
        location = Location.objects.create(name="Test")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=location,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=75,
            temperature_unit="F",
            short_forecast="Sunny",
            wind_speed=10,
        )

        admin = DailyForecastAdmin(DailyForecast, AdminSite())
        result = admin.temperature_display(forecast)
        assert "75°F" in result

    def test_wind_info_display(self):
        """Test wind info display."""
        location = Location.objects.create(name="Test")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=location,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=75,
            short_forecast="Sunny",
            wind_speed=15,
            wind_direction="NW",
        )

        admin = DailyForecastAdmin(DailyForecast, AdminSite())
        result = admin.wind_info(forecast)
        assert "15 mph" in result
        assert "NW" in result

    def test_wind_info_no_direction(self):
        """Test wind info display without direction."""
        location = Location.objects.create(name="Test")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=location,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=75,
            short_forecast="Sunny",
            wind_speed=10,
        )

        admin = DailyForecastAdmin(DailyForecast, AdminSite())
        result = admin.wind_info(forecast)
        assert result == "10 mph"


@pytest.mark.django_db
class TestHourlyForecastAdmin:
    """Test HourlyForecastAdmin."""

    def test_location_name_display(self):
        """Test location name display."""
        location = Location.objects.create(name="Seattle")
        today = timezone.now().date()
        forecast = HourlyForecast.objects.create(
            location=location,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(14, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(15, 0))),
            is_daytime=True,
            temperature=72,
            short_forecast="Partly Cloudy",
            wind_speed=8,
        )

        admin = HourlyForecastAdmin(HourlyForecast, AdminSite())
        result = admin.location_name(forecast)
        assert result == "Seattle"

    def test_temperature_display(self):
        """Test temperature display."""
        location = Location.objects.create(name="Test")
        today = timezone.now().date()
        forecast = HourlyForecast.objects.create(
            location=location,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(14, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(15, 0))),
            is_daytime=True,
            temperature=68,
            temperature_unit="F",
            short_forecast="Clear",
            wind_speed=5,
        )

        admin = HourlyForecastAdmin(HourlyForecast, AdminSite())
        result = admin.temperature_display(forecast)
        assert "68°F" in result


@pytest.mark.django_db
class TestWeatherAlertAdmin:
    """Test WeatherAlertAdmin."""

    def test_location_name_display(self):
        """Test location name display."""
        location = Location.objects.create(name="Danger Zone")
        alert = WeatherAlert.objects.create(
            location=location,
            event="Severe Thunderstorm Warning",
            severity="Severe",
            urgency="Immediate",
            headline="Severe Thunderstorm Warning",
            description="Take shelter immediately",
            instruction="Seek shelter in a sturdy building",
            onset=timezone.now(),
            expires=timezone.now() + timezone.timedelta(hours=2),
        )

        admin = WeatherAlertAdmin(WeatherAlert, AdminSite())
        result = admin.location_name(alert)
        assert result == "Danger Zone"

    def test_alert_type_display(self):
        """Test alert type display with severity coloring."""
        location = Location.objects.create(name="Test")
        alert = WeatherAlert.objects.create(
            location=location,
            event="Tornado Warning",
            severity="Extreme",
            urgency="Immediate",
            headline="Tornado Warning",
            description="Tornado sighted",
            instruction="Take shelter immediately",
            onset=timezone.now(),
            expires=timezone.now() + timezone.timedelta(hours=1),
        )

        admin = WeatherAlertAdmin(WeatherAlert, AdminSite())
        result = admin.alert_type(alert)
        assert "Extreme" in result
        assert "Tornado Warning" in result
        # Check for color coding
        assert "color:" in result or "background:" in result or "style" in result

    def test_active_status_yes(self):
        """Test active status display for active alert."""
        location = Location.objects.create(name="Test")
        # Alert expires in future - active
        alert = WeatherAlert.objects.create(
            location=location,
            event="Heat Advisory",
            severity="Moderate",
            urgency="Expected",
            headline="Heat Advisory",
            description="Hot weather expected",
            instruction="Stay hydrated",
            onset=timezone.now(),
            expires=timezone.now() + timezone.timedelta(hours=24),
        )

        admin = WeatherAlertAdmin(WeatherAlert, AdminSite())
        result = admin.active_status(alert)
        assert "Yes" in result or "✓" in result or "check" in result.lower()

    def test_active_status_no(self):
        """Test active status display for expired alert."""
        location = Location.objects.create(name="Test")
        # Alert expired in past - not active
        alert = WeatherAlert.objects.create(
            location=location,
            event="Frost Advisory",
            severity="Minor",
            urgency="Expected",
            headline="Frost Advisory",
            description="Frost expected",
            instruction="Cover plants",
            onset=timezone.now() - timezone.timedelta(hours=48),
            expires=timezone.now() - timezone.timedelta(hours=24),
        )

        admin = WeatherAlertAdmin(WeatherAlert, AdminSite())
        result = admin.active_status(alert)
        assert "No" in result or "✗" in result or "times" in result.lower()
