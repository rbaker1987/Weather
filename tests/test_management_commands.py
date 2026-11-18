"""Tests for weather management commands."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from weather.models import Location


@pytest.mark.django_db
class TestUpdateForecastsCommand:
    def test_specific_locations_report_success_and_failure(self):
        successful = Location.objects.create(name="Success")
        failed = Location.objects.create(name="Failure")
        output = StringIO()
        results = {
            str(successful.id): {
                "success": True,
                "daily_forecasts": 3,
                "hourly_forecasts": 8,
            },
            str(failed.id): {"success": False, "error": "service unavailable"},
        }

        def update(location):
            return results[str(location.id)]

        with patch(
            "weather.management.commands.update_forecasts.SyncWeatherService.update_forecasts_for_location",
            side_effect=update,
        ):
            call_command(
                "update_forecasts",
                locations=[str(successful.id), str(failed.id)],
                verbose=True,
                stdout=output,
            )

        text = output.getvalue()
        assert "Success: 3 daily, 8 hourly forecasts" in text
        assert "Failure: service unavailable" in text

    def test_specific_locations_require_valid_ids(self):
        with pytest.raises(CommandError, match="No valid locations found"):
            call_command("update_forecasts", locations=[str(uuid4())])

    def test_all_locations_without_force_only_updates_stale_locations(self):
        stale = Location.objects.create(
            name="Stale", last_forecast_update=timezone.now() - timedelta(hours=2)
        )
        Location.objects.create(name="Never Updated")
        Location.objects.create(
            name="Fresh", last_forecast_update=timezone.now() - timedelta(minutes=5)
        )
        output = StringIO()

        with patch(
            "weather.management.commands.update_forecasts.SyncWeatherService.bulk_update_forecasts",
            return_value={"success": True, "total_locations": 2, "results": []},
        ) as bulk_update:
            call_command("update_forecasts", stdout=output)

        ids = bulk_update.call_args.args[0]
        assert str(stale.id) in ids
        assert len(ids) == 2
        assert "Bulk update completed for 2 locations" in output.getvalue()

    def test_force_with_no_locations_reports_warning(self):
        output = StringIO()

        call_command("update_forecasts", force=True, stdout=output)

        assert "No locations need updating" in output.getvalue()

    def test_bulk_failure_and_verbose_results_are_reported(self):
        location = Location.objects.create(name="Verbose")
        output = StringIO()
        result = {
            "success": True,
            "total_locations": 1,
            "results": [
                {
                    "location": location.name,
                    "result": {"success": False, "error": "timeout"},
                }
            ],
        }

        with patch(
            "weather.management.commands.update_forecasts.SyncWeatherService.bulk_update_forecasts",
            return_value=result,
        ):
            call_command("update_forecasts", force=True, verbose=True, stdout=output)

        assert "Verbose: ERROR - timeout" in output.getvalue()

        output = StringIO()
        with patch(
            "weather.management.commands.update_forecasts.SyncWeatherService.bulk_update_forecasts",
            return_value={"success": False},
        ):
            call_command("update_forecasts", force=True, stdout=output)

        assert "Bulk update failed" in output.getvalue()
