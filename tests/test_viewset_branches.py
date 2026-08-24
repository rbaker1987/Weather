"""Tests for remaining deterministic viewset and export branches."""

from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from weather.models import CurrentConditions, DailyForecast, Location


@pytest.mark.django_db
class TestGeocodingActions:
    def test_geocode_search_valid_and_empty_results(self):
        response = Mock()
        response.json.side_effect = [
            [{"lat": "30.2", "lon": "-97.7", "display_name": "Austin"}],
            [],
        ]
        response.raise_for_status.return_value = None

        with patch("requests.get", return_value=response):
            found = APIClient().get(
                "/api/locations/geocode_search/", {"q": "Austin"}
            )
            empty = APIClient().get(
                "/api/locations/geocode_search/", {"q": "Nowhere"}
            )

        assert found.status_code == 200
        assert found.data["results"][0]["lat"] == 30.2
        assert empty.data == {"results": []}

    def test_geocode_search_validates_query_and_handles_request_error(self):
        client = APIClient()
        missing = client.get("/api/locations/geocode_search/")

        with patch(
            "requests.get", side_effect=__import__("requests").RequestException("down")
        ):
            failed = client.get("/api/locations/geocode_search/", {"q": "Austin"})

        assert missing.status_code == 400
        assert failed.status_code == 503

    def test_geocode_reverse_success_and_missing_coordinates(self):
        response = Mock()
        response.json.return_value = {
            "address": {"city": "Austin"},
            "display_name": "Austin, TX",
        }
        response.raise_for_status.return_value = None
        client = APIClient()

        with patch("requests.get", return_value=response):
            found = client.get(
                "/api/locations/geocode_reverse/", {"lat": "30", "lon": "-97"}
            )

        missing = client.get("/api/locations/geocode_reverse/", {"lat": "30"})
        assert found.data["address"]["city"] == "Austin"
        assert missing.status_code == 400


@pytest.mark.django_db
class TestCurrentConditionsActions:
    def test_by_location_validates_missing_and_unknown_locations(self):
        client = APIClient()
        missing = client.get("/api/current-conditions/by_location/")
        unknown = client.get(
            "/api/current-conditions/by_location/", {"location_id": str(uuid4())}
        )

        assert missing.status_code == 400
        assert unknown.status_code == 404

    def test_by_location_returns_cached_conditions(self):
        location = Location.objects.create(name="Austin")
        conditions = CurrentConditions.objects.create(
            location=location,
            temperature=72,
            condition="Clear",
            wind_speed=5,
            humidity=50,
            last_observation_time=timezone.now(),
        )

        with patch(
            "weather.services.CurrentConditionsService.get_or_fetch_current_conditions",
            return_value=conditions,
        ) as fetch:
            response = APIClient().get(
                "/api/current-conditions/by_location/",
                {"location_id": str(location.id), "refresh": "true"},
            )

        assert response.status_code == 200
        assert response.data["temperature"] == 72
        fetch.assert_called_once_with(location, force_refresh=True)

    def test_by_location_returns_unavailable_and_for_locations_filters(self):
        location = Location.objects.create(name="Austin")
        client = APIClient()
        with patch(
            "weather.services.CurrentConditionsService.get_or_fetch_current_conditions",
            return_value=None,
        ):
            unavailable = client.get(
                "/api/current-conditions/by_location/",
                {"location_id": str(location.id)},
            )
        missing = client.get("/api/current-conditions/for_locations/")

        assert unavailable.status_code == 503
        assert missing.status_code == 400


@pytest.mark.django_db
class TestForecastAndExportBranches:
    def test_forecasts_post_validates_payload(self):
        location = Location.objects.create(name="Austin")
        client = APIClient()
        session = client.session
        session["location_ids"] = [str(location.id)]
        session.save()
        base = f"/api/locations/{location.id}/forecasts/"

        missing_date = client.post(base, {}, format="json")
        bad_date = client.post(base, {"date": "bad"}, format="json")
        missing_temp = client.post(base, {"date": "2026-08-24"}, format="json")

        assert missing_date.status_code == 400
        assert bad_date.status_code == 400
        assert missing_temp.status_code == 400

    def test_export_requires_locations_and_exports_kml_coordinates(self):
        client = APIClient()
        missing = client.post("/api/export/", {}, format="json")
        location = Location.objects.create(
            name="Austin", latitude=30.2, longitude=-97.7, zip_code="78701"
        )

        kml = client.post(
            "/api/export/",
            {"format": "kml", "locations": [str(location.id)]},
            format="json",
        )

        assert missing.status_code == 400
        assert kml.status_code == 200
        assert "Austin" in kml.content.decode()
        assert kml["Content-Disposition"].endswith('weather_locations.kml"')

    def test_hourly_and_daily_viewsets_filter_by_location_and_dates(self):
        location = Location.objects.create(name="Austin", zip_code="78701")
        today = timezone.now().date()
        DailyForecast.objects.create(
            location=location,
            forecast_date=today,
            period_start=timezone.now(),
            period_end=timezone.now() + timedelta(hours=12),
            temperature=75,
            short_forecast="Sunny",
            wind_speed=5,
        )

        daily = APIClient().get(
            "/api/daily-forecasts/",
            {
                "start_date": today.isoformat(),
                "end_date": today.isoformat(),
                "location": "78701",
            },
        )

        assert daily.status_code == 200
        assert len(daily.data) == 1
