"""Tests for weather management commands."""

from datetime import timedelta
from io import StringIO
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from weather.management.commands.populate_climate_normals import (
    Command as PopulateClimateNormalsCommand,
)
from weather.models import Location


@pytest.mark.django_db
class TestPopulateClimateNormalsCommand:
    def test_populates_locations_with_coordinates(self):
        location = Location.objects.create(name="Austin", latitude=30, longitude=-97)
        output = StringIO()

        with patch.object(
            PopulateClimateNormalsCommand,
            "_fetch_climate_normals",
            return_value=(85.5, 64.5),
        ):
            call_command("populate_climate_normals", stdout=output)

        location.refresh_from_db()
        assert location.avg_high_temp == 85.5
        assert location.avg_low_temp == 64.5
        assert "Climate normals population complete" in output.getvalue()

    def test_location_id_limits_population(self):
        selected = Location.objects.create(name="Selected", latitude=30, longitude=-97)
        Location.objects.create(name="Other", latitude=31, longitude=-98)
        output = StringIO()

        with patch.object(
            PopulateClimateNormalsCommand,
            "_fetch_climate_normals",
            return_value=(80, 60),
        ) as fetch:
            call_command(
                "populate_climate_normals",
                location_id=str(selected.id),
                stdout=output,
            )

        assert fetch.call_count == 1
        assert "Processing 1 location(s)" in output.getvalue()

    def test_reports_unavailable_data_and_location_errors(self):
        unavailable = Location.objects.create(
            name="Unavailable", latitude=30, longitude=-97
        )
        broken = Location.objects.create(name="Broken", latitude=31, longitude=-98)
        output = StringIO()

        with patch.object(
            PopulateClimateNormalsCommand,
            "_fetch_climate_normals",
            side_effect=lambda _latitude, longitude: (
                (None, None)
                if longitude == -97
                else (_ for _ in ()).throw(RuntimeError("bad response"))
            ),
        ):
            call_command("populate_climate_normals", stdout=output)

        unavailable.refresh_from_db()
        broken.refresh_from_db()
        text = output.getvalue()
        assert unavailable.avg_high_temp is None
        assert "Could not retrieve climate data" in text
        assert "Error for Broken: bad response" in text

    def test_fetch_climate_normals_returns_averages(self):
        command = PopulateClimateNormalsCommand()
        points = Mock()
        points.json.return_value = {"properties": {"forecast": "forecast-url"}}
        forecast = Mock()
        forecast.json.return_value = {
            "properties": {
                "periods": [
                    {"isDaytime": True, "temperature": 80},
                    {"isDaytime": False, "temperature": 60},
                ]
            }
        }

        with patch(
            "weather.management.commands.populate_climate_normals.requests.get",
            side_effect=[points, forecast],
        ):
            result = command._fetch_climate_normals(30, -97)

        assert result == (80.0, 60.0)

    @pytest.mark.parametrize(
        "payload",
        [{}, {"properties": {}}, {"properties": {"forecast": "url"}}],
    )
    def test_fetch_climate_normals_handles_incomplete_responses(self, payload):
        command = PopulateClimateNormalsCommand()
        response = Mock()
        response.json.return_value = payload

        with patch(
            "weather.management.commands.populate_climate_normals.requests.get",
            return_value=response,
        ):
            result = command._fetch_climate_normals(30, -97)

        assert result == (None, None)

    def test_fetch_climate_normals_handles_request_error(self):
        import requests

        command = PopulateClimateNormalsCommand()
        with patch(
            "weather.management.commands.populate_climate_normals.requests.get",
            side_effect=requests.RequestException("offline"),
        ):
            result = command._fetch_climate_normals(30, -97)

        assert result == (None, None)


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
