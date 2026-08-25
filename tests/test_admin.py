"""Tests for weather Django admin display helpers and actions."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.utils import timezone

from weather.admin import (
    DailyForecastAdmin,
    ForecastRequestAdmin,
    HourlyForecastAdmin,
    LocationAdmin,
    WeatherAlertAdmin,
)
from weather.models import (
    DailyForecast,
    ForecastRequest,
    HourlyForecast,
    Location,
    WeatherAlert,
)


@pytest.fixture
def admin_site():
    return AdminSite()


@pytest.mark.django_db
class TestLocationAdmin:
    def test_display_helpers_and_actions(self, admin_site):
        admin = LocationAdmin(Location, admin_site)
        with_coordinates = Location.objects.create(
            name="Austin", latitude=30.2672, longitude=-97.7431
        )
        without_coordinates = Location.objects.create(name="Unknown")

        assert admin.coordinates_display(with_coordinates) == "30.2672, -97.7431"
        assert admin.coordinates_display(without_coordinates) == "No coordinates"
        assert admin.forecast_count(with_coordinates) == "0 forecasts"
        assert admin.last_update(without_coordinates) == "Never"

        request = Mock()
        queryset = Location.objects.filter(pk=with_coordinates.pk)
        admin.update_forecasts(request, queryset)
        with_coordinates.refresh_from_db()
        assert with_coordinates.last_forecast_update is not None

        admin.deactivate_locations(request, queryset)
        with_coordinates.refresh_from_db()
        assert with_coordinates.is_active is False


@pytest.mark.django_db
class TestForecastAdmins:
    def test_daily_forecast_display_helpers(self, admin_site):
        location = Location.objects.create(name="Austin")
        admin = DailyForecastAdmin(DailyForecast, admin_site)
        forecast = DailyForecast.objects.create(
            location=location,
            forecast_date=timezone.now().date(),
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(hours=12),
            temperature=75,
            high_temperature=80,
            low_temperature=65,
            short_forecast="Sunny",
            wind_speed=10,
            wind_direction="N",
            wind_gust=20,
        )

        assert "Austin" in str(admin.location_name(forecast))
        assert admin.temperature_display(forecast) == "65°F - 80°F"
        assert admin.wind_info(forecast) == "10 mph N (gusts 20)"

    def test_daily_forecast_fallback_display(self, admin_site):
        location = Location.objects.create(name="Austin")
        admin = DailyForecastAdmin(DailyForecast, admin_site)
        forecast = DailyForecast.objects.create(
            location=location,
            forecast_date=timezone.now().date(),
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(hours=1),
            temperature=75,
            short_forecast="Sunny",
            wind_speed=0,
        )

        assert admin.temperature_display(forecast) == "75°F"
        assert admin.wind_info(forecast) == "0 mph"

    def test_hourly_forecast_display_helpers(self, admin_site):
        location = Location.objects.create(name="Austin")
        admin = HourlyForecastAdmin(HourlyForecast, admin_site)
        forecast = HourlyForecast.objects.create(
            location=location,
            forecast_date=timezone.now().date(),
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(hours=1),
            temperature=75,
            apparent_temperature=68,
            short_forecast="Sunny",
            wind_speed=5,
        )

        assert admin.location_name(forecast) == "Austin"
        assert admin.temperature_display(forecast) == "75°F (feels 68°)"


@pytest.mark.django_db
class TestAlertAndRequestAdmins:
    def test_alert_admin_helpers_and_action(self, admin_site):
        location = Location.objects.create(name="Austin")
        admin = WeatherAlertAdmin(WeatherAlert, admin_site)
        alert = WeatherAlert.objects.create(
            location=location,
            nws_alert_id="ADMIN-ALERT",
            event="Watch",
            expires=timezone.now() - timedelta(hours=1),
            is_active=True,
        )

        assert admin.location_name(alert) == "Austin"
        assert admin.is_expired(alert) is True
        admin.deactivate_alerts(Mock(), WeatherAlert.objects.filter(pk=alert.pk))
        alert.refresh_from_db()
        assert alert.is_active is False

    def test_forecast_request_admin_helpers(self, admin_site):
        user = User.objects.create_user(username="admin-user")
        location = Location.objects.create(name="Austin")
        request = ForecastRequest.objects.create(
            session_key="abcdefghijklmno",
            request_type="daily",
            response_time_ms=1500,
        )
        request.locations_requested.add(location)
        admin = ForecastRequestAdmin(ForecastRequest, admin_site)

        assert admin.session_display(request) == "abcdefghijkl"
        assert admin.location_count(request) == 1
        assert admin.response_time_display(request) == "1.50s"
        assert admin.location_names(request) == "Austin"

        request.response_time_ms = 250
        assert admin.response_time_display(request) == "250ms"
        request.response_time_ms = None
        assert admin.response_time_display(request) == "N/A"
        request.session_key = ""
        assert admin.session_display(request) == "Unknown"
        assert user.username == "admin-user"
