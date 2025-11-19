"""Extended tests for signals, serializers, and additional view actions."""

import json
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from weather.models import DailyForecast, HourlyForecast, Location, WeatherAlert
from weather.serializers import (
    BulkForecastRequestSerializer,
    LocationSerializer,
    WeatherAlertSerializer,
)


@pytest.mark.django_db
class TestLocationSignals:
    def test_coordinate_validation_valid(self):
        """Valid coordinates should save successfully."""
        loc = Location.objects.create(
            name="Valid", latitude=Decimal("45.5"), longitude=Decimal("-122.6")
        )
        assert loc.latitude == Decimal("45.5")

    def test_coordinate_validation_invalid_latitude(self):
        """Invalid latitude should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid latitude"):
            Location.objects.create(
                name="BadLat", latitude=Decimal("91.0"), longitude=Decimal("0.0")
            )

    def test_coordinate_validation_invalid_longitude(self):
        """Invalid longitude should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid longitude"):
            Location.objects.create(
                name="BadLon", latitude=Decimal("0.0"), longitude=Decimal("181.0")
            )


@pytest.mark.django_db
class TestLocationModel:
    def test_set_as_favorite(self):
        """Test setting location as favorite."""
        loc1 = Location.objects.create(name="TestLoc1")
        loc2 = Location.objects.create(name="TestLoc2")
        assert not loc1.is_favorite
        assert not loc2.is_favorite
        loc1.set_as_favorite()
        loc1.refresh_from_db()
        assert loc1.is_favorite
        # Setting loc2 as favorite should unset loc1
        loc2.set_as_favorite()
        loc1.refresh_from_db()
        loc2.refresh_from_db()
        assert not loc1.is_favorite
        assert loc2.is_favorite

    def test_location_display_name_with_custom(self):
        """Test display name prefers custom_name."""
        loc = Location.objects.create(name="Original", custom_name="Custom")
        assert loc.display_name == "Custom"

    def test_location_display_name_without_custom(self):
        """Test display name falls back to name."""
        loc = Location.objects.create(name="Original")
        assert loc.display_name == "Original"


@pytest.mark.django_db
class TestForecastSignals:
    def test_apparent_temperature_calculated(self):
        """Test apparent temperature auto-calculation."""
        loc = Location.objects.create(name="Test")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=85,
            short_forecast="Hot",
            wind_speed=5,
        )
        # Should auto-calculate when temp >= 80
        assert forecast.apparent_temperature is not None
        assert forecast.apparent_temperature >= 85


@pytest.mark.django_db
class TestSerializers:
    def test_location_serializer_valid(self):
        """Test LocationSerializer with valid data."""
        data = {
            "name": "SerializerTest",
            "latitude": "40.7128",
            "longitude": "-74.0060",
            "zip_code": "10001",
        }
        serializer = LocationSerializer(data=data)
        assert serializer.is_valid()
        location = serializer.save()
        assert location.name == "SerializerTest"

    def test_location_serializer_missing_name(self):
        """Test LocationSerializer requires name."""
        data = {"latitude": "40.0", "longitude": "-74.0"}
        serializer = LocationSerializer(data=data)
        assert not serializer.is_valid()
        assert "name" in serializer.errors

    def test_bulk_forecast_serializer_valid(self):
        """Test BulkForecastRequestSerializer validation."""
        data = {
            "locations": ["Austin", "Dallas"],
            "forecast_type": "daily",
            "days": 5,
            "include_alerts": True,
        }
        serializer = BulkForecastRequestSerializer(data=data)
        assert serializer.is_valid()

    def test_bulk_forecast_serializer_invalid_type(self):
        """Test BulkForecastRequestSerializer rejects invalid forecast_type."""
        data = {
            "locations": ["Austin"],
            "forecast_type": "invalid",
            "days": 3,
            "include_alerts": False,
        }
        serializer = BulkForecastRequestSerializer(data=data)
        assert not serializer.is_valid()

    def test_weather_alert_serializer(self):
        """Test WeatherAlertSerializer."""
        loc = Location.objects.create(name="AlertTest")
        alert = WeatherAlert.objects.create(
            location=loc,
            nws_alert_id="TEST123",
            event="Severe Thunderstorm Warning",
            headline="Dangerous Storm",
            description="Take shelter immediately",
            severity=WeatherAlert.Severity.SEVERE,
            urgency=WeatherAlert.Urgency.IMMEDIATE,
            expires=timezone.now() + timedelta(hours=2),
        )
        serializer = WeatherAlertSerializer(alert)
        data = serializer.data
        assert data["event"] == "Severe Thunderstorm Warning"
        assert data["severity"] == "severe"


@pytest.mark.django_db
class TestLocationViewSetActions:
    def test_update_forecast_without_coordinates(self, client):
        """Test update_forecast action fails without coordinates."""
        loc = Location.objects.create(name="NoCoords")
        sess = client.session
        sess["location_ids"] = [str(loc.id)]
        sess.save()

        resp = client.post(f"/api/locations/{loc.id}/update_forecast/")
        assert resp.status_code == 400
        body = resp.json()
        assert body.get("status") == "error"

    def test_forecasts_action_hourly(self, client):
        """Test forecasts action returns hourly forecasts."""
        loc = Location.objects.create(name="HourlyTest")
        today = timezone.now().date()
        HourlyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(8, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(9, 0))),
            is_daytime=True,
            temperature=72,
            short_forecast="Clear",
            wind_speed=5,
        )
        sess = client.session
        sess["location_ids"] = [str(loc.id)]
        sess.save()

        resp = client.get(f"/api/locations/{loc.id}/forecasts/?type=hourly&days=1")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_forecasts_action_daily_default(self, client):
        """Test forecasts action defaults to daily."""
        loc = Location.objects.create(name="DailyTest")
        today = timezone.now().date()
        DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=75,
            short_forecast="Sunny",
            wind_speed=8,
        )
        sess = client.session
        sess["location_ids"] = [str(loc.id)]
        sess.save()

        resp = client.get(f"/api/locations/{loc.id}/forecasts/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_alerts_action(self, client):
        """Test alerts action returns active alerts."""
        loc = Location.objects.create(name="AlertLoc")
        WeatherAlert.objects.create(
            location=loc,
            nws_alert_id="ALERT1",
            event="Test Alert",
            headline="Test",
            description="Test description",
            severity=WeatherAlert.Severity.MODERATE,
            urgency=WeatherAlert.Urgency.EXPECTED,
            expires=timezone.now() + timedelta(hours=3),
            is_active=True,
        )
        sess = client.session
        sess["location_ids"] = [str(loc.id)]
        sess.save()

        resp = client.get(f"/api/locations/{loc.id}/alerts/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["event"] == "Test Alert"


@pytest.mark.django_db
class TestExportAPIFormats:
    def test_export_kml(self, client):
        """Test KML export format."""
        loc = Location.objects.create(
            name="KMLTest", latitude=Decimal("30.0"), longitude=Decimal("-97.0")
        )
        payload = {"format": "kml", "locations": [str(loc.id)]}
        resp = client.post(
            "/api/export/", data=json.dumps(payload), content_type="application/json"
        )
        assert resp.status_code == 200
        assert "application/vnd.google-earth.kml+xml" in resp["Content-Type"]
        content = resp.content.decode()
        assert "KMLTest" in content
        assert "<coordinates>" in content

    def test_export_no_locations(self, client):
        """Test export fails without locations."""
        payload = {"format": "json", "locations": []}
        resp = client.post(
            "/api/export/", data=json.dumps(payload), content_type="application/json"
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body


@pytest.mark.django_db
class TestWeatherAlertModel:
    def test_alert_is_expired(self):
        """Test is_expired property."""
        loc = Location.objects.create(name="ExpiredTest")
        # Expired alert
        expired_alert = WeatherAlert.objects.create(
            location=loc,
            nws_alert_id="EXP1",
            event="Old",
            headline="Old",
            description="",
            severity=WeatherAlert.Severity.MINOR,
            urgency=WeatherAlert.Urgency.EXPECTED,
            expires=timezone.now() - timedelta(hours=1),
        )
        assert expired_alert.is_expired

        # Active alert
        active_alert = WeatherAlert.objects.create(
            location=loc,
            nws_alert_id="ACT1",
            event="Current",
            headline="Current",
            description="",
            severity=WeatherAlert.Severity.SEVERE,
            urgency=WeatherAlert.Urgency.IMMEDIATE,
            expires=timezone.now() + timedelta(hours=1),
        )
        assert not active_alert.is_expired
