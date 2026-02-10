"""Comprehensive API tests for DRF endpoints in weather app."""

import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from weather.models import CurrentConditions, DailyForecast, Location, WeatherAlert


def add_location_to_session(client, location):
    """Helper to add location to session so it's visible in queryset."""
    session = client.session
    ids = session.get("location_ids", [])
    ids = [str(x) for x in ids]
    lid = str(location.id)
    if lid not in ids:
        ids.append(lid)
    session["location_ids"] = ids
    session.save()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestLocationAPI:
    def test_list_filters_by_session_location_ids(self, client):
        l1 = Location.objects.create(name="A")
        l2 = Location.objects.create(name="B")
        Location.objects.create(name="C")
        sess = client.session
        sess["location_ids"] = [str(l1.id), str(l2.id)]
        sess.save()

        resp = client.get("/api/locations/")
        assert resp.status_code == 200
        data = resp.json()
        # Only A and B present
        names = {item["name"] for item in data}
        assert names == {"A", "B"}

    def test_ensure_browser_location_creates_and_sets_session(self, client):
        payload = {
            "name": "My Location",
            "latitude": 30.1,
            "longitude": -97.7,
        }
        resp = client.post(
            "/api/locations/ensure_browser_location/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "success"
        # Confirm the new id is in session
        sess_ids = client.session.get("location_ids", [])
        assert body["location_id"] in sess_ids


@pytest.mark.django_db
class TestExportAPI:
    def _make_forecast(self, location, date):
        return DailyForecast.objects.create(
            location=location,
            forecast_date=date,
            period_start=timezone.make_aware(datetime.combine(date, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(date, time(18, 0))),
            is_daytime=True,
            temperature=72,
            short_forecast="Sunny",
            wind_speed=5,
        )

    def test_export_json(self, client):
        loc = Location.objects.create(name="Austin")
        today = timezone.now().date()
        self._make_forecast(loc, today)

        payload = {"format": "json", "locations": [str(loc.id)]}
        resp = client.post(
            "/api/export/", data=json.dumps(payload), content_type="application/json"
        )
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("application/json")
        data = resp.json()
        assert isinstance(data, list) and data
        assert data[0]["name"] == "Austin"
        assert isinstance(data[0].get("forecasts"), list)

    def test_export_csv(self, client):
        loc = Location.objects.create(name="Austin")
        today = timezone.now().date()
        self._make_forecast(loc, today)

        payload = {"format": "csv", "locations": [str(loc.id)]}
        resp = client.post(
            "/api/export/", data=json.dumps(payload), content_type="application/json"
        )
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/csv")
        content = resp.content.decode()
        assert (
            "Location,Date,High Temp,Low Temp,Forecast,Wind Speed,Wind Direction"
            in content
        )
        assert "Austin" in content


@pytest.mark.django_db
class TestStatsAPI:
    def test_stats_counts(self, client):
        loc = Location.objects.create(name="StatsVille")
        today = timezone.now().date()
        # Seed data for counts
        DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=70,
            short_forecast="Cloudy",
            wind_speed=4,
        )
        WeatherAlert.objects.create(
            location=loc,
            nws_alert_id="ALX",
            event="Advisory",
            headline="",
            description="",
            severity=WeatherAlert.Severity.MINOR,
            urgency=WeatherAlert.Urgency.EXPECTED,
            expires=timezone.now() + timedelta(hours=2),
            is_active=True,
        )

        resp = client.get("/api/stats/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_locations"] >= 1
        assert body["total_forecasts"] >= 1
        assert body["active_alerts"] >= 1
        assert "recent_averages" in body


@pytest.mark.django_db
class TestBulkForecastAPI:
    def test_bulk_forecast_with_existing_location(self, client):
        loc = Location.objects.create(name="BulkCity")
        today = timezone.now().date()
        # Seed a forecast so the response has payload
        DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=68,
            short_forecast="Mostly sunny",
            wind_speed=8,
        )

        payload = {
            "locations": ["BulkCity"],
            "forecast_type": "daily",
            "days": 3,
            "include_alerts": False,
        }
        resp = client.post(
            "/api/bulk-forecast/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "success"
        assert isinstance(body.get("locations"), list)

    def test_bulk_forecast_with_nonexistent_locations(self, api_client):
        """Test bulk forecast with locations that don't exist."""
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = api_client.post(
            "/api/bulk-forecast/", {"location_ids": [fake_uuid]}, format="json"
        )
        assert response.status_code == 400

    def test_bulk_forecast_success_with_alerts(self, api_client):
        """Bulk forecast returns data for existing location including alerts."""
        loc = Location.objects.create(name="Bulk City")
        WeatherAlert.objects.create(
            location=loc,
            nws_alert_id="BULK1",
            event="Advisory",
            headline="Heads up",
            description="",
            severity="moderate",
            urgency="expected",
            onset=timezone.now(),
            expires=timezone.now() + timedelta(hours=2),
            is_active=True,
            raw_data={},
        )
        payload = {
            "locations": ["Bulk City"],
            "forecast_type": "both",
            "days": 1,
            "include_alerts": True,
        }
        resp = api_client.post("/api/bulk-forecast/", payload, format="json")
        assert resp.status_code == 200
        assert resp.data["status"] == "success"


@pytest.mark.django_db
class TestLocationActions:
    """Test LocationViewSet custom actions."""

    def test_forecasts_get_daily_and_hourly(self, api_client):
        loc = Location.objects.create(
            name="L1", latitude=Decimal("1.0"), longitude=Decimal("2.0")
        )
        add_location_to_session(api_client, loc)
        today = timezone.now().date()
        DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=70,
            short_forecast="Sunny",
            wind_speed=5,
        )
        r1 = api_client.get(f"/api/locations/{loc.pk}/forecasts/?type=daily&days=3")
        assert r1.status_code == 200 and len(r1.data) >= 1
        r2 = api_client.get(f"/api/locations/{loc.pk}/forecasts/?type=hourly&days=1")
        assert r2.status_code == 200

    def test_forecasts_post_create_custom(self, api_client):
        loc = Location.objects.create(name="L2")
        add_location_to_session(api_client, loc)
        payload = {
            "date": timezone.now().date().isoformat(),
            "is_daytime": True,
            "temperature": 65,
            "short_forecast": "Partly Cloudy",
        }
        r = api_client.post(
            f"/api/locations/{loc.pk}/forecasts/", payload, format="json"
        )
        assert r.status_code in (200, 201)
        assert DailyForecast.objects.filter(location=loc).exists()

    def test_alerts_list(self, api_client):
        loc = Location.objects.create(name="L3")
        add_location_to_session(api_client, loc)
        WeatherAlert.objects.create(
            location=loc,
            event="Heat Advisory",
            severity="moderate",
            urgency="expected",
            headline="Heat",
            description="Hot",
            onset=timezone.now(),
            expires=timezone.now() + timedelta(hours=1),
            is_active=True,
            raw_data={},
        )
        r = api_client.get(f"/api/locations/{loc.pk}/alerts/")
        assert r.status_code == 200 and len(r.data) == 1

    def test_ensure_browser_location_success(self, api_client):
        payload = {"name": "Here", "latitude": 10.0, "longitude": 20.0}
        with patch("weather.services.SyncWeatherService.update_forecasts_for_location"):
            r = api_client.post(
                "/api/locations/ensure_browser_location/", payload, format="json"
            )
        assert r.status_code == 200 and r.data["status"] == "success"
        assert "location_ids" in api_client.session

    def test_ensure_browser_location_updates_existing_current(self, api_client):
        """Test updating an existing current location with new coords."""
        Location.objects.create(
            name="Old",
            latitude=Decimal("30.0"),
            longitude=Decimal("-95.0"),
            is_current_location=True,
        )
        payload = {"name": "Updated", "latitude": 35.0, "longitude": -90.0}
        with patch("weather.services.SyncWeatherService.update_forecasts_for_location"):
            r = api_client.post(
                "/api/locations/ensure_browser_location/", payload, format="json"
            )
        assert r.status_code == 200

    def test_ensure_browser_location_missing_coords(self, api_client):
        r = api_client.post(
            "/api/locations/ensure_browser_location/", {"name": "bad"}, format="json"
        )
        assert r.status_code == 400

    def test_reorder_success(self, api_client):
        l1, l2 = Location.objects.create(name="A"), Location.objects.create(name="B")
        order = [str(l2.id), str(l1.id)]
        r = api_client.post(
            "/api/locations/reorder/", {"location_order": order}, format="json"
        )
        assert r.status_code == 200
        l1.refresh_from_db()
        l2.refresh_from_db()
        assert l2.display_order == 0 and l1.display_order == 1

    def test_reorder_missing_order(self, api_client):
        r = api_client.post("/api/locations/reorder/", {}, format="json")
        assert r.status_code == 400

    def test_reorder_exception_handling(self, api_client):
        """Trigger exception in reorder to hit error branch."""
        with patch(
            "weather.models.Location.objects.filter", side_effect=Exception("db error")
        ):
            r = api_client.post(
                "/api/locations/reorder/",
                {"location_order": ["bad-uuid"]},
                format="json",
            )
        assert r.status_code == 500

    def test_clear_all(self, api_client):
        Location.objects.create(name="X")
        Location.objects.create(name="Y")
        r = api_client.post("/api/locations/clear_all/", {}, format="json")
        assert r.status_code == 200 and r.data["status"] == "success"

    def test_set_current_and_toggle(self, api_client):
        loc = Location.objects.create(name="Home")
        add_location_to_session(api_client, loc)
        r1 = api_client.post(f"/api/locations/{loc.pk}/set_current/")
        assert r1.status_code == 200
        loc.refresh_from_db()
        assert loc.is_current_location and loc.is_enabled
        r2 = api_client.post(f"/api/locations/{loc.pk}/toggle_enabled/")
        assert r2.status_code == 200


@pytest.mark.django_db
class TestUpdateForecastAction:
    """Test update_forecast action with various scenarios."""

    def test_update_forecast_no_coordinates_no_zip(self, api_client):
        """Test update_forecast when location has no coordinates and no zip code."""
        location = Location.objects.create(name="No Coords")
        add_location_to_session(api_client, location)
        response = api_client.post(f"/api/locations/{location.pk}/update_forecast/")
        assert response.status_code == 400
        assert "coordinates or zip code" in str(response.data).lower()

    def test_update_forecast_with_current_conditions(self, api_client):
        """Test update_forecast fetches current conditions from observation station."""
        location = Location.objects.create(
            name="Test Location",
            latitude=Decimal("45.5152"),
            longitude=Decimal("-122.6784"),
        )
        add_location_to_session(api_client, location)

        mock_grid = Mock(status_code=200)
        mock_grid.json.return_value = {
            "properties": {
                "gridId": "PQR",
                "gridX": 100,
                "gridY": 50,
                "forecast": "https://api.weather.gov/gridpoints/PQR/100,50/forecast",
                "observationStations": "https://api.weather.gov/gridpoints/PQR/100,50/stations",
            }
        }
        mock_stations = Mock(status_code=200)
        mock_stations.json.return_value = {
            "features": [{"properties": {"stationIdentifier": "KPDX"}}]
        }
        mock_obs = Mock(status_code=200)
        mock_obs.json.return_value = {
            "properties": {
                "temperature": {"value": 20.5},
                "textDescription": "Partly Cloudy",
                "relativeHumidity": {"value": 65},
                "windSpeed": {"value": 16.09},
                "windDirection": {"value": 315},
                "timestamp": "2025-11-19T14:30:00Z",
            }
        }
        mock_forecast = Mock(status_code=200)
        mock_forecast.json.return_value = {"properties": {"periods": []}}

        with patch(
            "requests.get",
            side_effect=[mock_grid, mock_stations, mock_obs, mock_forecast],
        ):
            response = api_client.post(f"/api/locations/{location.pk}/update_forecast/")

        assert response.status_code == 200
        location.refresh_from_db()
        cc = location.current_conditions_cache
        assert cc.temperature == 68  # 20.5C = 68.9F ≈ 68F
        assert cc.condition == "Partly Cloudy"

    def test_update_forecast_processes_alerts(self, api_client):
        """Test update_forecast processes alert features and updates counts."""
        location = Location.objects.create(
            name="Alerts Loc", latitude=Decimal("35.0"), longitude=Decimal("-90.0")
        )
        add_location_to_session(api_client, location)

        mock_grid = Mock(status_code=200)
        mock_grid.json.return_value = {
            "properties": {
                "gridId": "MEG",
                "gridX": 10,
                "gridY": 20,
                "forecast": "https://api.weather.gov/gridpoints/MEG/10,20/forecast",
                "observationStations": "https://api.weather.gov/gridpoints/MEG/10,20/stations",
            }
        }
        mock_stations = Mock(status_code=200)
        mock_stations.json.return_value = {
            "features": [{"properties": {"stationIdentifier": "KMEM"}}]
        }
        mock_obs = Mock(status_code=200)
        mock_obs.json.return_value = {
            "properties": {
                "temperature": {"value": 10},
                "textDescription": "Cloudy",
                "relativeHumidity": {"value": 50},
                "windSpeed": {"value": 0},
                "windDirection": {"value": 180},
                "timestamp": "2025-01-01T00:00:00Z",
            }
        }
        mock_forecast = Mock(status_code=200)
        mock_forecast.json.return_value = {"properties": {"periods": []}}
        mock_alerts = Mock(status_code=200)
        mock_alerts.json.return_value = {
            "features": [
                {
                    "properties": {
                        "id": "ALERT1",
                        "event": "Warning",
                        "headline": "Severe",
                        "description": "Desc",
                        "severity": "Severe",
                        "urgency": "Immediate",
                        "onset": "2025-01-01T01:00:00Z",
                        "expires": "2025-01-01T02:00:00Z",
                    }
                }
            ]
        }

        with patch(
            "requests.get",
            side_effect=[
                mock_grid,
                mock_stations,
                mock_obs,
                mock_forecast,
                mock_alerts,
            ],
        ):
            resp = api_client.post(f"/api/locations/{location.pk}/update_forecast/")
        assert resp.status_code == 200 and "alerts_created" in resp.data

    def test_update_forecast_handles_request_exception(self, api_client):
        """Trigger requests exception to hit error branch."""
        location = Location.objects.create(
            name="Err Loc", latitude=Decimal("40.0"), longitude=Decimal("-80.0")
        )
        add_location_to_session(api_client, location)

        grid = Mock(status_code=200)
        grid.json.return_value = {
            "properties": {"forecast": "x", "gridId": "A", "gridX": 1, "gridY": 2}
        }

        with patch("requests.get") as mock_get:
            import requests

            mock_get.side_effect = [grid, requests.exceptions.RequestException("boom")]
            r = api_client.post(f"/api/locations/{location.pk}/update_forecast/")
        assert r.status_code == 500

    def test_update_forecast_creates_periods_with_wind_range(self, api_client):
        """Ensure forecast periods are created and wind range parsed."""
        location = Location.objects.create(
            name="Periods Loc", latitude=Decimal("41.0"), longitude=Decimal("-81.0")
        )
        add_location_to_session(api_client, location)
        today = timezone.now().date()

        mock_grid = Mock(status_code=200)
        mock_grid.json.return_value = {
            "properties": {
                "gridId": "CLE",
                "gridX": 5,
                "gridY": 6,
                "forecast": "https://api.weather.gov/gridpoints/CLE/5,6/forecast",
                "observationStations": "https://api.weather.gov/gridpoints/CLE/5,6/stations",
            }
        }
        mock_stations = Mock(status_code=200)
        mock_stations.json.return_value = {
            "features": [{"properties": {"stationIdentifier": "KCLE"}}]
        }
        mock_obs = Mock(status_code=200)
        mock_obs.json.return_value = {
            "properties": {
                "temperature": {"value": 15},
                "relativeHumidity": {"value": 50},
                "windSpeed": {"value": 8},
                "windDirection": {"value": 90},
                "timestamp": f"{today}T00:00:00Z",
            }
        }
        mock_fcst = Mock(status_code=200)
        mock_fcst.json.return_value = {
            "properties": {
                "periods": [
                    {
                        "startTime": f"{today}T06:00:00Z",
                        "endTime": f"{today}T18:00:00Z",
                        "isDaytime": True,
                        "temperature": 70,
                        "temperatureUnit": "F",
                        "windSpeed": "10 to 15 mph",
                        "windDirection": "NE",
                        "shortForecast": "Sunny",
                        "detailedForecast": "Nice day",
                        "probabilityOfPrecipitation": {"value": 10},
                    }
                ]
            }
        }
        mock_alerts = Mock(status_code=200)
        mock_alerts.json.return_value = {"features": []}

        with patch(
            "requests.get",
            side_effect=[mock_grid, mock_stations, mock_obs, mock_fcst, mock_alerts],
        ):
            resp = api_client.post(f"/api/locations/{location.pk}/update_forecast/")
        assert resp.status_code == 200
        assert DailyForecast.objects.filter(location=location).count() == 1

    def test_update_forecast_geocodes_zip(self, api_client):
        """Test update_forecast geocodes location with zip code but no coords."""
        location = Location.objects.create(name="Zip Loc", zip_code="10001")
        add_location_to_session(api_client, location)

        mock_geo = Mock(status_code=200)
        mock_geo.json.return_value = [{"lat": "40.75", "lon": "-73.99"}]
        mock_grid = Mock(status_code=200)
        mock_grid.json.return_value = {
            "properties": {
                "gridId": "NYC",
                "gridX": 10,
                "gridY": 20,
                "forecast": "https://api.weather.gov/gridpoints/NYC/10,20/forecast",
                "observationStations": "https://api.weather.gov/gridpoints/NYC/10,20/stations",
            }
        }
        mock_stations = Mock(status_code=200)
        mock_stations.json.return_value = {"features": []}
        mock_fcst = Mock(status_code=200)
        mock_fcst.json.return_value = {"properties": {"periods": []}}
        mock_alerts = Mock(status_code=200)
        mock_alerts.json.return_value = {"features": []}

        with patch(
            "requests.get",
            side_effect=[mock_geo, mock_grid, mock_stations, mock_fcst, mock_alerts],
        ):
            resp = api_client.post(f"/api/locations/{location.pk}/update_forecast/")

        assert resp.status_code == 200
        location.refresh_from_db()
        assert location.latitude == Decimal("40.75")


@pytest.mark.django_db
class TestExportAPIExtended:
    """Additional export tests."""

    def test_export_kml_no_coordinates(self, api_client):
        """Test KML export with location that has no coordinates."""
        location = Location.objects.create(name="No Coords Location")
        response = api_client.post(
            "/api/export/",
            {"format": "kml", "locations": [str(location.id)]},
            format="json",
        )
        assert response.status_code == 200

    def test_export_json_with_forecasts(self, api_client):
        loc = Location.objects.create(name="JSON Loc")
        today = timezone.now().date()
        DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=70,
            short_forecast="OK",
            wind_speed=5,
        )
        resp = api_client.post(
            "/api/export/",
            {"format": "json", "locations": [str(loc.id)]},
            format="json",
        )
        assert resp.status_code == 200
        assert "application/json" in resp["Content-Type"]


@pytest.mark.django_db
class TestWeatherStatsExtended:
    """Additional stats tests."""

    def test_weather_stats_with_forecast_data(self, api_client):
        """Test weather stats calculation with forecast data."""
        location = Location.objects.create(name="Stats Location")
        today = timezone.now().date()

        for i, temp in enumerate([65, 70, 75, 80, 85]):
            DailyForecast.objects.create(
                location=location,
                forecast_date=today + timedelta(days=i),
                period_start=timezone.make_aware(
                    datetime.combine(today + timedelta(days=i), time(6, 0))
                ),
                period_end=timezone.make_aware(
                    datetime.combine(today + timedelta(days=i), time(18, 0))
                ),
                is_daytime=True,
                temperature=temp,
                short_forecast="Test",
                wind_speed=10,
            )

        response = api_client.get("/api/stats/")
        assert response.status_code == 200
        assert "total_forecasts" in response.data

    def test_weather_stats_no_data(self, api_client):
        """Test weather stats with no forecast data."""
        response = api_client.get("/api/stats/")
        assert response.status_code == 200
