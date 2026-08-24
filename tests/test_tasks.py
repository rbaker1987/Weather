"""Tests for background weather tasks."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from weather import tasks
from weather.models import CurrentConditions, DailyForecast, Location, WeatherAlert


@pytest.mark.django_db
class TestEnqueueHelpers:
    def test_enqueue_helpers_run_directly_when_celery_disabled(self):
        location = Location.objects.create(name="Austin", latitude=30, longitude=-97)
        with (
            patch("weather.services.CurrentConditionsService") as conditions,
            patch("weather.services.ForecastService") as forecasts,
            patch("weather.services.AlertsService") as alerts,
            patch("weather.tasks._celery_enabled", return_value=False),
        ):
            assert tasks.enqueue_current_conditions(str(location.id)) == "direct"
            assert tasks.enqueue_forecasts(str(location.id)) == "direct"
            assert tasks.enqueue_alerts(str(location.id)) == "direct"

        conditions.fetch_and_cache_current_conditions.assert_called_once_with(location)
        assert forecasts.get_or_fetch_hourly_forecasts.called
        assert forecasts.get_or_fetch_daily_forecasts.called
        alerts.fetch_and_cache_alerts.assert_called_once_with(location)

    def test_enqueue_helpers_queue_when_celery_enabled(self):
        location_id = str(uuid4())
        with (
            patch("weather.tasks._celery_enabled", return_value=True),
            patch.object(tasks.update_current_conditions_for_location, "delay") as current,
            patch.object(tasks.update_forecasts_for_location, "delay") as forecast,
            patch.object(tasks.update_alerts_for_location, "delay") as alert,
        ):
            assert tasks.enqueue_current_conditions(location_id) == "queued"
            assert tasks.enqueue_forecasts(location_id) == "queued"
            assert tasks.enqueue_alerts(location_id) == "queued"

        current.assert_called_once_with(location_id)
        forecast.assert_called_once_with(location_id)
        alert.assert_called_once_with(location_id)


@pytest.mark.django_db
class TestBackgroundTasks:
    def test_update_location_forecast_success_and_not_found(self):
        location = Location.objects.create(name="Austin")
        result = {"success": True, "daily_forecasts": 2, "hourly_forecasts": 4}
        with patch(
            "weather.tasks.SyncWeatherService.update_forecasts_for_location",
            return_value=result,
        ):
            assert tasks.update_location_forecast.run(str(location.id)) == result

        missing = tasks.update_location_forecast.run(str(uuid4()))
        assert missing == {"error": "Location not found"}

    def test_bulk_update_forecasts_records_failure(self):
        location = Location.objects.create(name="Austin")
        with patch(
            "weather.tasks.SyncWeatherService.bulk_update_forecasts",
            return_value={"success": False},
        ):
            result = tasks.bulk_update_forecasts.run([str(location.id)])

        assert result == {"success": False}
        request = location.forecast_requests.get(request_type="bulk_background_update")
        assert request.status == request.RequestStatus.FAILED
        assert request.error_message == "Bulk update failed"

    def test_periodic_forecast_updates_handles_stale_and_fresh_locations(self):
        stale = Location.objects.create(name="Stale")
        fresh = Location.objects.create(
            name="Fresh", last_forecast_update=timezone.now()
        )
        with patch.object(tasks.bulk_update_forecasts, "delay", return_value="queued") as delay:
            result = tasks.periodic_forecast_updates.run()

        assert result == "queued"
        delay.assert_called_once()
        assert str(stale.id) in [str(value) for value in delay.call_args.args[0]]
        assert str(fresh.id) not in [str(value) for value in delay.call_args.args[0]]

        Location.objects.filter(pk=stale.pk).update(last_forecast_update=timezone.now())
        assert tasks.periodic_forecast_updates.run() == {"message": "No updates needed"}

    def test_cache_statistics_and_process_alerts(self):
        location = Location.objects.create(name="Austin")
        DailyForecast.objects.create(
            location=location,
            forecast_date=timezone.now().date(),
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(hours=12),
            temperature=70,
            short_forecast="Sunny",
            wind_speed=5,
        )
        WeatherAlert.objects.create(
            location=location,
            nws_alert_id="EXPIRED-TASK",
            event="Old",
            expires=timezone.now() - timedelta(hours=1),
            is_active=True,
        )

        stats = tasks.cache_weather_statistics.run()
        assert stats["total_locations"] == 1
        assert cache.get("weather_dashboard_stats")["total_forecasts"] == 1

        result = tasks.process_weather_alerts.run()
        assert result == {"expired_alerts_deactivated": 1}

    def test_generate_forecast_report_daily_and_hourly(self):
        location = Location.objects.create(name="Austin")
        today = timezone.now().date()
        DailyForecast.objects.create(
            location=location,
            forecast_date=today,
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(hours=12),
            temperature=70,
            short_forecast="Sunny",
            wind_speed=5,
        )
        result = tasks.generate_forecast_report.run([str(location.id)], "daily")
        assert result["locations"] == 1
        assert cache.get(result["cache_key"])[0]["forecast_count"] == 1

        hourly = tasks.generate_forecast_report.run([str(location.id)], "hourly")
        assert hourly["report_type"] == "hourly"

    def test_cleanup_cached_weather_data_removes_all_weather_rows(self):
        location = Location.objects.create(name="Austin")
        CurrentConditions.objects.create(
            location=location,
            temperature=70,
            condition="Sunny",
            wind_speed=5,
            humidity=50,
            last_observation_time=timezone.now(),
        )

        result = tasks.cleanup_cached_weather_data.run()

        assert result["current_conditions_deleted"] == 1
        assert CurrentConditions.objects.count() == 0
