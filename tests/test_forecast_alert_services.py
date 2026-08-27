"""Tests for forecast and alert cache-aware services."""

from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.core.cache import cache
from django.utils import timezone

from weather.models import HourlyForecast, Location, WeatherAlert
from weather.services import AlertsService, ForecastService


def response(payload):
    result = Mock()
    result.json.return_value = payload
    result.raise_for_status.return_value = None
    return result


@pytest.mark.django_db
class TestForecastService:
    def test_hourly_service_fetches_when_no_recent_forecast(self):
        location = Location.objects.create(name="Hourly")

        with patch(
            "weather.services.SyncWeatherService.update_forecasts_for_location"
        ) as update:
            result = ForecastService.get_or_fetch_hourly_forecasts(location)

        update.assert_called_once_with(location)
        assert list(result) == []

    def test_hourly_service_returns_recent_forecasts_without_fetching(self):
        location = Location.objects.create(name="Hourly")
        now = timezone.now()
        forecast = HourlyForecast.objects.create(
            location=location,
            forecast_date=now.date(),
            period_start=now + timedelta(hours=1),
            period_end=now + timedelta(hours=2),
            temperature=70,
            short_forecast="Clear",
            wind_speed=5,
            last_api_update=now,
        )

        with patch(
            "weather.services.SyncWeatherService.update_forecasts_for_location"
        ) as update:
            result = ForecastService.get_or_fetch_hourly_forecasts(location)

        update.assert_not_called()
        assert list(result) == [forecast]

    def test_daily_service_fetches_when_forced(self):
        location = Location.objects.create(name="Daily")

        with patch(
            "weather.services.SyncWeatherService.update_forecasts_for_location"
        ) as update:
            result = ForecastService.get_or_fetch_daily_forecasts(
                location, force_refresh=True
            )

        update.assert_called_once_with(location)
        assert list(result) == []


@pytest.mark.django_db
class TestAlertsService:
    def test_alert_service_returns_fresh_cached_alerts(self):
        location = Location.objects.create(name="Alerts")
        alert = WeatherAlert.objects.create(
            location=location,
            nws_alert_id="FRESH-1",
            event="Watch",
            expires=timezone.now() + timedelta(hours=1),
            is_active=True,
        )
        cache.set(f"alerts:last_fetch:{location.id}", timezone.now(), 900)

        with patch.object(AlertsService, "fetch_and_cache_alerts") as fetch:
            result = AlertsService.get_or_fetch_alerts(location)

        fetch.assert_not_called()
        assert list(result) == [alert]

    def test_alert_service_fetches_when_cache_is_stale(self):
        location = Location.objects.create(name="Alerts")
        cache.set(
            f"alerts:last_fetch:{location.id}",
            timezone.now() - timedelta(minutes=16),
            900,
        )

        with patch.object(AlertsService, "fetch_and_cache_alerts", return_value=[]) as fetch:
            result = AlertsService.get_or_fetch_alerts(location)

        fetch.assert_called_once_with(location)
        assert result == []

    def test_fetch_alerts_deactivates_old_and_saves_new_alerts(self):
        location = Location.objects.create(name="Alerts", latitude=30, longitude=-97)
        old = WeatherAlert.objects.create(
            location=location,
            nws_alert_id="OLD",
            event="Old",
            expires=timezone.now() + timedelta(hours=1),
            is_active=True,
        )
        payload = {
            "features": [
                {
                    "properties": {
                        "id": "NEW",
                        "event": "Heat Advisory",
                        "headline": "Hot",
                        "description": "Drink water",
                        "severity": "Severe",
                        "urgency": "Expected",
                        "onset": (timezone.now() - timedelta(hours=1)).isoformat(),
                        "expires": (timezone.now() + timedelta(hours=1)).isoformat(),
                    }
                },
                {"properties": {}},
            ]
        }

        with patch(
            "requests.get",
            return_value=response(payload),
        ):
            result = AlertsService.fetch_and_cache_alerts(location)

        old.refresh_from_db()
        new = WeatherAlert.objects.get(nws_alert_id="NEW")
        assert old.is_active is False
        assert new.event == "Heat Advisory"
        assert new.severity == "severe"
        assert list(result) == [new]
        assert cache.get(f"alerts:last_fetch:{location.id}") is not None
