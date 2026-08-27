"""Tests for remaining background task branches."""

from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from weather import tasks
from weather.models import CurrentConditions, Location


@pytest.mark.django_db
class TestPeriodicTasks:
    def test_update_all_current_conditions_reports_success_failed_and_error(self):
        success = Location.objects.create(name="Success", latitude=30, longitude=-97)
        failed = Location.objects.create(name="Failed", latitude=31, longitude=-98)
        Location.objects.create(name="Error", latitude=32, longitude=-99)
        CurrentConditions.objects.create(
            location=success,
            temperature=70,
            condition="Clear",
            wind_speed=5,
            humidity=50,
            last_observation_time=timezone.now(),
        )

        def fetch(location):
            if location == success:
                return location.current_conditions_cache
            if location == failed:
                return None
            raise RuntimeError("service error")

        with patch(
            "weather.services.CurrentConditionsService.fetch_and_cache_current_conditions",
            side_effect=fetch,
        ):
            result = tasks.update_all_current_conditions.run()

        assert {item["status"] for item in result} == {"success", "failed", "error"}

    def test_update_all_forecasts_reports_success_and_error(self):
        Location.objects.create(name="Success", latitude=30, longitude=-97)
        Location.objects.create(name="Error", latitude=32, longitude=-99)
        hourly = Mock()
        hourly.count.return_value = 2
        daily = Mock()
        daily.count.return_value = 1

        with (
            patch(
                "weather.services.ForecastService.get_or_fetch_hourly_forecasts",
                side_effect=lambda location, **_kwargs: (
                    (_ for _ in ()).throw(RuntimeError("forecast error"))
                    if location.name == "Error"
                    else hourly
                ),
            ),
            patch(
                "weather.services.ForecastService.get_or_fetch_daily_forecasts",
                return_value=daily,
            ),
        ):
            result = tasks.update_all_forecasts.run()

        assert len(result) == 2
        assert any(item["status"] == "error" for item in result)
        assert any(item["status"] == "success" for item in result)

    def test_update_all_alerts_reports_success_and_error(self):
        Location.objects.create(name="Success", latitude=30, longitude=-97)
        Location.objects.create(name="Error", latitude=32, longitude=-99)
        alerts = Mock()
        alerts.count.return_value = 1

        with patch(
            "weather.services.AlertsService.fetch_and_cache_alerts",
            side_effect=[alerts, RuntimeError("alert error")],
        ):
            result = tasks.update_all_alerts.run()

        assert len(result) == 2
        assert result[0]["status"] == "success"
        assert result[1]["status"] == "error"


@pytest.mark.django_db
class TestSingleLocationTasks:
    def test_update_current_conditions_success_and_not_found(self):
        location = Location.objects.create(name="Austin")
        conditions = Mock(temperature=72)
        with patch(
            "weather.services.CurrentConditionsService.fetch_and_cache_current_conditions",
            return_value=conditions,
        ):
            result = tasks.update_current_conditions_for_location.run(str(location.id))

        assert result == {
            "location": "Austin",
            "status": "success",
            "temperature": 72,
        }
        assert tasks.update_current_conditions_for_location.run(str(uuid4()))["status"] == "not_found"

    def test_update_forecasts_and_alerts_success_and_not_found(self):
        location = Location.objects.create(name="Austin")
        hourly = Mock()
        hourly.count.return_value = 3
        daily = Mock()
        daily.count.return_value = 2
        alerts = Mock()
        alerts.count.return_value = 1

        with (
            patch("weather.services.ForecastService.get_or_fetch_hourly_forecasts", return_value=hourly),
            patch("weather.services.ForecastService.get_or_fetch_daily_forecasts", return_value=daily),
        ):
            forecast_result = tasks.update_forecasts_for_location.run(str(location.id))
        with patch(
            "weather.services.AlertsService.fetch_and_cache_alerts", return_value=alerts
        ):
            alert_result = tasks.update_alerts_for_location.run(str(location.id))

        assert forecast_result["hourly_count"] == 3
        assert alert_result["alert_count"] == 1
        assert tasks.update_forecasts_for_location.run(str(uuid4()))["status"] == "not_found"
        assert tasks.update_alerts_for_location.run(str(uuid4()))["status"] == "not_found"


@pytest.mark.django_db
def test_generate_forecast_report_uses_all_locations_limit_and_cache():
    Location.objects.create(name="Austin")
    result = tasks.generate_forecast_report.run()

    assert result["locations"] == 1
    assert cache.get(result["cache_key"])[0]["location"] == "Austin"


@pytest.mark.django_db
def test_cleanup_old_forecasts_task_returns_cleanup_result():
    with patch(
        "weather.services.WeatherIntegrationService.cleanup_old_forecasts",
        new=AsyncMock(return_value={"daily_deleted": 0, "hourly_deleted": 0}),
    ):
        result = tasks.cleanup_old_forecasts.run()

    assert result == {"daily_deleted": 0, "hourly_deleted": 0}
