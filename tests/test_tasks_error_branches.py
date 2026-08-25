"""Tests for background-task failure and retry branches."""

from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from celery.exceptions import Retry
from django.core.cache import cache
from django.utils import timezone

from weather import tasks
from weather.models import ForecastRequest, Location, WeatherAlert


@pytest.mark.django_db
class TestTaskErrorBranches:
    def test_update_location_forecast_records_service_failure(self):
        location = Location.objects.create(name="Austin")
        with patch(
            "weather.tasks.SyncWeatherService.update_forecasts_for_location",
            return_value={"success": False, "error": "offline"},
        ):
            result = tasks.update_location_forecast.run(str(location.id))

        assert result["success"] is False
        request = ForecastRequest.objects.get(request_type="background_update")
        assert request.status == ForecastRequest.RequestStatus.FAILED
        assert request.error_message == "offline"

    def test_update_location_forecast_retries_unexpected_errors(self):
        location = Location.objects.create(name="Austin")
        with (
            patch(
                "weather.tasks.SyncWeatherService.update_forecasts_for_location",
                side_effect=RuntimeError("offline"),
            ),
            patch.object(tasks.update_location_forecast, "retry", side_effect=Retry),
            pytest.raises(Retry),
        ):
            tasks.update_location_forecast.run(str(location.id))

    def test_bulk_update_forecasts_records_failure(self):
        with patch(
            "weather.tasks.SyncWeatherService.bulk_update_forecasts",
            return_value={"success": False},
        ):
            result = tasks.bulk_update_forecasts.run()

        assert result == {"success": False}
        request = ForecastRequest.objects.get(request_type="bulk_background_update")
        assert request.status == ForecastRequest.RequestStatus.FAILED

    def test_periodic_forecast_updates_queues_stale_location(self):
        location = Location.objects.create(name="Stale")
        queued = Mock(return_value="queued")
        with patch.object(tasks.bulk_update_forecasts, "delay", new=queued):
            result = tasks.periodic_forecast_updates.run()

        assert result == "queued"
        queued.assert_called_once_with([location.id])

    def test_process_weather_alerts_deactivates_expired_alerts(self):
        location = Location.objects.create(name="Austin")
        WeatherAlert.objects.create(
            location=location,
            nws_alert_id="EXPIRED-ERROR-BRANCH",
            event="Warning",
            expires=timezone.now() - timedelta(hours=1),
            is_active=True,
        )

        result = tasks.process_weather_alerts.run()

        assert result["expired_alerts_deactivated"] == 1

    def test_generate_forecast_report_caches_empty_report(self):
        result = tasks.generate_forecast_report.run([str(uuid4())])

        assert result["locations"] == 0
        assert cache.get(result["cache_key"]) == []
