"""API tests for DRF endpoints in weather app."""

import json
from datetime import datetime, time, timedelta

import pytest
from django.utils import timezone

from weather.models import DailyForecast, Location, WeatherAlert


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
        resp = client.post("/api/locations/ensure_browser_location/", data=json.dumps(payload), content_type="application/json")
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
        resp = client.post("/api/export/", data=json.dumps(payload), content_type="application/json")
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
        resp = client.post("/api/export/", data=json.dumps(payload), content_type="application/json")
        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("text/csv")
        content = resp.content.decode()
        assert "Location,Date,High Temp,Low Temp,Forecast,Wind Speed,Wind Direction" in content
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
            temperature=75,
            short_forecast="Windy",
            wind_speed=8,
        )

        payload = {
            "locations": ["BulkCity"],
            "forecast_type": "daily",
            "days": 3,
            "include_alerts": False,
        }
        resp = client.post("/api/bulk-forecast/", data=json.dumps(payload), content_type="application/json")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "success"
        assert body.get("locations") and isinstance(body["locations"], list)
        first = body["locations"][0]
        assert "location" in first
        assert "forecasts" in first and "daily" in first["forecasts"]
