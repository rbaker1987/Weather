"""Tests for remaining deterministic viewset and export branches."""

from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from weather.models import CurrentConditions, DailyForecast, Location, WeatherAlert


def add_location_to_session(client, location):
    session = client.session
    session["location_ids"] = [str(location.id)]
    session.save()


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

    def test_geocode_reverse_reports_service_error(self):
        with patch(
            "requests.get", side_effect=__import__("requests").RequestException("down")
        ):
            response = APIClient().get(
                "/api/locations/geocode_reverse/", {"lat": "30", "lon": "-97"}
            )

        assert response.status_code == 503

    def test_geocode_search_reports_unexpected_error(self):
        with patch("requests.get", side_effect=ValueError("bad payload")):
            response = APIClient().get(
                "/api/locations/geocode_search/", {"q": "Austin"}
            )

        assert response.status_code == 500

    def test_geocode_reverse_reports_unexpected_error(self):
        with patch("requests.get", side_effect=ValueError("bad payload")):
            response = APIClient().get(
                "/api/locations/geocode_reverse/", {"lat": "30", "lon": "-97"}
            )

        assert response.status_code == 500


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
    def test_clear_all_deletes_active_locations(self):
        Location.objects.create(name="Active", is_active=True)
        Location.objects.create(name="Inactive", is_active=False)

        response = APIClient().post("/api/locations/clear_all/")

        assert response.status_code == 200
        assert response.data["deleted"] == 1
        assert not Location.objects.filter(is_active=True).exists()

    def test_ensure_browser_location_updates_existing_current_location(self):
        location = Location.objects.create(
            name="Old", latitude=1, longitude=2, is_current_location=True
        )
        client = APIClient()
        add_location_to_session(client, location)

        with patch("weather.tasks.enqueue_current_conditions"), patch(
            "weather.tasks.enqueue_forecasts"
        ), patch("weather.tasks.enqueue_alerts"):
            response = client.post(
                "/api/locations/ensure_browser_location/",
                {"name": "New", "latitude": 30.1, "longitude": -97.7},
                format="json",
            )

        location.refresh_from_db()
        assert response.status_code == 200
        assert response.data["location_id"] == str(location.id)
        assert location.name == "New"
        assert float(location.latitude) == 30.1

    def test_location_actions_set_current_toggle_and_reorder(self):
        first = Location.objects.create(name="First", is_current_location=True)
        second = Location.objects.create(name="Second", is_enabled=True)
        client = APIClient()
        add_location_to_session(client, second)

        current = client.post(f"/api/locations/{second.id}/set_current/")
        toggled = client.post(f"/api/locations/{second.id}/toggle_enabled/")
        reordered = client.post(
            "/api/locations/reorder/", {"location_order": [str(first.id), str(second.id)]}, format="json"
        )

        assert current.status_code == 200
        assert toggled.data["is_enabled"] is False
        assert reordered.status_code == 200
        second.refresh_from_db()
        assert second.is_current_location is True
        assert second.display_order == 1

    def test_reorder_requires_location_order(self):
        response = APIClient().post("/api/locations/reorder/", {}, format="json")

        assert response.status_code == 400

    def test_update_forecast_rejects_location_without_coordinates_or_zip(self):
        location = Location.objects.create(name="Missing coordinates")
        client = APIClient()
        add_location_to_session(client, location)

        response = client.post(f"/api/locations/{location.id}/update_forecast/")

        assert response.status_code == 400
        assert "does not have coordinates" in response.data["message"]

    def test_update_forecast_reports_geocoding_failure(self):
        location = Location.objects.create(name="Unknown", zip_code="00000")
        client = APIClient()
        add_location_to_session(client, location)
        geocode = Mock()
        geocode.json.return_value = []
        geocode.raise_for_status.return_value = None

        with patch("requests.get", return_value=geocode):
            response = client.post(
                f"/api/locations/{location.id}/update_forecast/"
            )

        assert response.status_code == 400
        assert "Could not geocode zip code" in response.data["message"]

    def test_update_forecast_reports_missing_forecast_url(self):
        location = Location.objects.create(
            name="Grid only", latitude=30, longitude=-97
        )
        client = APIClient()
        add_location_to_session(client, location)
        grid = Mock()
        grid.json.return_value = {"properties": {"gridId": "FWD"}}
        grid.raise_for_status.return_value = None

        with patch("requests.get", return_value=grid):
            response = client.post(
                f"/api/locations/{location.id}/update_forecast/"
            )

        assert response.status_code == 500
        assert response.data["message"] == "Forecast URL not found."

    def test_update_forecast_stores_conditions_forecast_and_alert(self):
        location = Location.objects.create(
            name="Austin", latitude=30, longitude=-97
        )
        client = APIClient()
        add_location_to_session(client, location)

        grid = Mock()
        grid.json.return_value = {
            "properties": {
                "gridId": "FWD",
                "gridX": 1,
                "gridY": 2,
                "forecast": "https://example.test/forecast",
                "observationStations": "https://example.test/stations",
            }
        }
        stations = Mock()
        stations.json.return_value = {
            "features": [{"properties": {"stationIdentifier": "KATT"}}]
        }
        observation = Mock()
        observation.json.return_value = {
            "properties": {
                "temperature": {"value": 20},
                "relativeHumidity": {"value": 60},
                "windSpeed": {"value": 10},
                "windGust": {"value": 20},
                "windDirection": {"value": 180},
                "textDescription": "Sunny",
                "dewpoint": {"value": 10},
                "timestamp": "2026-08-25T12:00:00Z",
            }
        }
        forecast = Mock()
        forecast.json.return_value = {
            "properties": {
                "periods": [
                    {
                        "startTime": "2026-08-25T06:00:00Z",
                        "endTime": "2026-08-25T18:00:00Z",
                        "isDaytime": True,
                        "temperature": 86,
                        "temperatureUnit": "F",
                        "windSpeed": "10 to 20 mph",
                        "windDirection": "S",
                        "shortForecast": "Sunny",
                        "detailedForecast": "Clear",
                        "probabilityOfPrecipitation": {"value": 10},
                    }
                ]
            }
        }
        alerts = Mock()
        alerts.json.return_value = {
            "features": [
                {
                    "properties": {
                        "id": "alert-1",
                        "event": "Heat Advisory",
                        "headline": "Heat",
                        "description": "Hot",
                        "severity": "Moderate",
                        "urgency": "Expected",
                        "onset": "2026-08-25T12:00:00Z",
                        "expires": "2026-08-26T12:00:00Z",
                    }
                }
            ]
        }
        for response in (grid, stations, observation, forecast, alerts):
            response.raise_for_status.return_value = None

        with patch(
            "requests.get",
            side_effect=[grid, stations, observation, forecast, alerts],
        ):
            response = client.post(
                f"/api/locations/{location.id}/update_forecast/"
            )

        assert response.status_code == 200
        assert response.data["periods_created"] == 1
        assert response.data["alerts_created"] == 1
        assert DailyForecast.objects.get(location=location).wind_speed == 15
        conditions = CurrentConditions.objects.get(location=location)
        assert conditions.temperature == 68
        assert conditions.wind_direction == "S"
        assert WeatherAlert.objects.get(nws_alert_id="alert-1").is_active is True

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
