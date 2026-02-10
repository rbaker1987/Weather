"""Tests for Django web interface views."""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from weather.models import CurrentConditions, DailyForecast, Location, WeatherAlert


@pytest.mark.django_db
class TestDashboardView:
    def test_dashboard_renders_with_locations_and_forecasts(self, client):
        session = client.session
        # Create locations
        loc1 = Location.objects.create(
            name="Home City",
            latitude=Decimal("30.0"),
            longitude=Decimal("-97.0"),
            is_current_location=True,
        )
        loc2 = Location.objects.create(
            name="Work City", latitude=Decimal("31.0"), longitude=Decimal("-98.0")
        )
        session["location_ids"] = [str(loc1.id), str(loc2.id)]
        session.save()

        # Create forecasts for favorite (current) location
        for i in range(3):
            day = timezone.now().date() + timedelta(days=i)
            DailyForecast.objects.create(
                location=loc1,
                forecast_date=day,
                period_start=timezone.make_aware(datetime.combine(day, time(6, 0))),
                period_end=timezone.make_aware(datetime.combine(day, time(18, 0))),
                is_daytime=True,
                temperature=70 + i,
                short_forecast="Sunny",
                wind_speed=5,
                nws_data_url="https://api.weather.gov/gridpoints/TEST/1,1/forecast",
            )
            DailyForecast.objects.create(
                location=loc1,
                forecast_date=day,
                period_start=timezone.make_aware(datetime.combine(day, time(18, 0))),
                period_end=timezone.make_aware(datetime.combine(day, time(23, 59))),
                is_daytime=False,
                temperature=60 + i,
                short_forecast="Clear",
                wind_speed=3,
                nws_data_url="https://api.weather.gov/gridpoints/TEST/1,1/forecast",
            )

        resp = client.get(reverse("weather:dashboard"))
        assert resp.status_code == 200
        assert "favorite_location" in resp.context
        assert resp.context["favorite_location"].id == loc1.id
        # 3 grouped days
        assert len(resp.context["daily_forecasts"]) >= 1


@pytest.mark.django_db
class TestAlertListView:
    def test_alert_list_filters_by_session_and_counts(self, client):
        session = client.session
        loc1 = Location.objects.create(name="A")
        loc2 = Location.objects.create(name="B")
        session["location_ids"] = [str(loc1.id)]
        session.save()

        # Create alerts
        WeatherAlert.objects.create(
            location=loc1,
            nws_alert_id="AL1",
            event="Warning",
            headline="Severe",
            description="",
            severity=WeatherAlert.Severity.SEVERE,
            urgency=WeatherAlert.Urgency.IMMEDIATE,
            expires=timezone.now() + timedelta(hours=1),
        )
        WeatherAlert.objects.create(
            location=loc1,
            nws_alert_id="AL2",
            event="Watch",
            headline="Moderate",
            description="",
            severity=WeatherAlert.Severity.MODERATE,
            urgency=WeatherAlert.Urgency.EXPECTED,
            expires=timezone.now() + timedelta(hours=1),
        )
        WeatherAlert.objects.create(
            location=loc2,
            nws_alert_id="AL3",
            event="Other",
            headline="Severe",
            description="",
            severity=WeatherAlert.Severity.SEVERE,
            urgency=WeatherAlert.Urgency.IMMEDIATE,
            expires=timezone.now() + timedelta(hours=1),
        )

        resp = client.get(reverse("weather:alert-list"))
        assert resp.status_code == 200
        alerts = list(resp.context["alerts"])
        # Only loc1 alerts should be present due to session filter
        assert all(a.location_id == loc1.id for a in alerts)
        assert resp.context["severe_extreme_count"] == 1
        assert resp.context["moderate_count"] == 1


@pytest.mark.django_db
class TestForecastListView:
    def test_forecast_list_groups_by_date_and_location(self, client, monkeypatch):
        session = client.session
        loc1 = Location.objects.create(name="A", is_enabled=True)
        loc2 = Location.objects.create(name="B", is_enabled=True)
        session["location_ids"] = [str(loc1.id), str(loc2.id)]
        session.save()

        today = timezone.now().date()
        # Create day/night pair per location for today
        for loc in (loc1, loc2):
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
            DailyForecast.objects.create(
                location=loc,
                forecast_date=today,
                period_start=timezone.make_aware(datetime.combine(today, time(18, 0))),
                period_end=timezone.make_aware(datetime.combine(today, time(23, 59))),
                is_daytime=False,
                temperature=60,
                short_forecast="Clear",
                wind_speed=3,
            )
        # Mark forecasts as recently updated to avoid service imports
        loc1.last_forecast_update = timezone.now()
        loc2.last_forecast_update = timezone.now()
        loc1.save(update_fields=["last_forecast_update"])
        loc2.save(update_fields=["last_forecast_update"])
        resp = client.get(reverse("weather:forecast-list"))
        assert resp.status_code == 200
        assert "grouped_by_date" in resp.context
        grouped = resp.context["grouped_by_date"]
        assert len(grouped) >= 1
        # Each date entry should have both locations
        assert len(grouped[0]["locations"]) == 2

    def test_forecast_list_triggers_refresh_fallback(self, client, monkeypatch):
        session = client.session
        loc = Location.objects.create(
            name="R1",
            is_enabled=True,
            latitude=Decimal("1.0"),
            longitude=Decimal("2.0"),
        )
        session["location_ids"] = [str(loc.id)]
        session.save()
        # Ensure no forecasts and stale update
        loc.last_forecast_update = None
        loc.save(update_fields=["last_forecast_update"])

        # Make service raise to force fallback
        monkeypatch.setattr(
            "weather.services.SyncWeatherService.update_forecasts_for_location",
            lambda *_: (_ for _ in ()).throw(Exception("fail")),
        )

        # Fallback creates a forecast for today
        def fake_refresh(location):
            today = timezone.now().date()
            DailyForecast.objects.update_or_create(
                location=location,
                forecast_date=today,
                period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
                period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
                defaults={
                    "is_daytime": True,
                    "temperature": 70,
                    "short_forecast": "OK",
                    "wind_speed": 3,
                },
            )
            return True

        monkeypatch.setattr(
            "weather.views._refresh_forecasts_for_location", fake_refresh
        )

        r = client.get(reverse("weather:forecast-list"))
        assert r.status_code == 200
        assert "grouped_by_date" in r.context

    def test_forecast_list_context_grouping_and_sorting(self, client):
        session = client.session
        l1 = Location.objects.create(
            name="Home", is_enabled=True, is_current_location=True, location_type="home"
        )
        l2 = Location.objects.create(name="Work", is_enabled=True, location_type="work")
        session["location_ids"] = [str(l1.id), str(l2.id)]
        session.save()

        today = timezone.now().date()
        tomorrow = today + timedelta(days=1)
        for loc in (l1, l2):
            for day in (today, tomorrow):
                DailyForecast.objects.create(
                    location=loc,
                    forecast_date=day,
                    period_start=timezone.make_aware(datetime.combine(day, time(6, 0))),
                    period_end=timezone.make_aware(datetime.combine(day, time(18, 0))),
                    is_daytime=True,
                    temperature=70,
                    short_forecast="Day",
                    wind_speed=5,
                )
                DailyForecast.objects.create(
                    location=loc,
                    forecast_date=day,
                    period_start=timezone.make_aware(
                        datetime.combine(day, time(18, 0))
                    ),
                    period_end=timezone.make_aware(
                        datetime.combine(day, time(23, 59, 59))
                    ),
                    is_daytime=False,
                    temperature=60,
                    short_forecast="Night",
                    wind_speed=3,
                )
        # Ensure current conditions exist to populate locations_with_current
        CurrentConditions.objects.create(
            location=l1, temperature=70, condition="Sunny",
            wind_speed=5, humidity=60, last_observation_time=timezone.now()
        )
        CurrentConditions.objects.create(
            location=l2, temperature=65, condition="Cloudy",
            wind_speed=3, humidity=55, last_observation_time=timezone.now()
        )

        resp = client.get(reverse("weather:forecast-list"))
        assert resp.status_code == 200
        assert (
            "grouped_by_date" in resp.context
            and len(resp.context["grouped_by_date"]) >= 2
        )
        assert "locations_with_current" in resp.context

    def test_refresh_forecasts_exception_path(self, client, monkeypatch):
        """Test _refresh_forecasts_for_location handles exception."""
        session = client.session
        loc = Location.objects.create(
            name="Fail",
            is_enabled=True,
            latitude=Decimal("1.0"),
            longitude=Decimal("2.0"),
        )
        session["location_ids"] = [str(loc.id)]
        session.save()
        loc.last_forecast_update = None
        loc.save(update_fields=["last_forecast_update"])

        # Mock requests.get to raise exception
        def bad_get(*args, **kwargs):
            raise Exception("network error")

        monkeypatch.setattr("requests.get", bad_get)
        # Should not crash, just return False and log
        from weather.views import _refresh_forecasts_for_location

        result = _refresh_forecasts_for_location(loc)
        assert result is False


@pytest.mark.django_db
class TestLocationListView:
    def test_location_list_fetches_current_conditions(self, client, monkeypatch):
        """Test location list triggers current conditions fetch for stale data."""
        session = client.session
        loc = Location.objects.create(
            name="Stale", latitude=Decimal("10.0"), longitude=Decimal("20.0")
        )
        session["location_ids"] = [str(loc.id)]
        session.save()
        # Create stale current conditions (> 15 min old)
        cc = CurrentConditions.objects.create(
            location=loc, temperature=65, condition="Rainy",
            wind_speed=10, humidity=75, last_observation_time=timezone.now()
        )
        cc.updated_at = timezone.now() - timedelta(minutes=20)
        cc.save()

        # Mock fetch to update temp
        def fake_fetch(location):
            cc = location.current_conditions_cache
            cc.temperature = 72
            cc.save()
            return True

        monkeypatch.setattr("weather.views.fetch_current_conditions", fake_fetch)

        r = client.get(reverse("weather:location-list"))
        assert r.status_code == 200
        loc.refresh_from_db()
        assert loc.current_conditions_cache.temperature == 72


@pytest.mark.django_db
class TestLocationDetailView:
    def test_location_detail_triggers_update_and_alerts(self, client, monkeypatch):
        loc = Location.objects.create(
            name="Needs Update", latitude=Decimal("10.0"), longitude=Decimal("20.0")
        )
        # force update needed
        loc.last_forecast_update = None
        loc.save(update_fields=["last_forecast_update"])

        today = timezone.now().date()
        # Avoid current conditions network by returning True
        monkeypatch.setattr(
            "weather.views.fetch_current_conditions", lambda _location: True
        )

        # Mock NWS endpoints for forecast and alerts
        class MockResp:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        grid_payload = {
            "properties": {
                "gridId": "XYZ",
                "gridX": 1,
                "gridY": 2,
                "forecast": "https://api.weather.gov/gridpoints/XYZ/1,2/forecast",
            }
        }
        forecast_payload = {
            "properties": {
                "periods": [
                    {
                        "startTime": f"{today}T06:00:00Z",
                        "endTime": f"{today}T18:00:00Z",
                        "isDaytime": True,
                        "temperature": 72,
                        "temperatureUnit": "F",
                        "windSpeed": "10 mph",
                        "windDirection": "S",
                        "shortForecast": "Sunny",
                        "detailedForecast": "Clear day",
                        "probabilityOfPrecipitation": {"value": 0},
                    }
                ]
            }
        }
        alerts_payload = {
            "features": [
                {
                    "properties": {
                        "id": "DL1",
                        "event": "Storm",
                        "headline": "Heads",
                        "description": "desc",
                        "severity": "Moderate",
                        "urgency": "Expected",
                        "onset": f"{today}T07:00:00Z",
                        "expires": f"{today}T08:00:00Z",
                    }
                }
            ]
        }

        def fake_get(url, headers=None, timeout=10):
            if "points" in url:
                return MockResp(grid_payload)
            if "forecast" in url:
                return MockResp(forecast_payload)
            if "alerts" in url:
                return MockResp(alerts_payload)
            return MockResp({})

        monkeypatch.setattr("requests.get", fake_get)

        r = client.get(f"/locations/{loc.pk}/")
        assert r.status_code == 200
        assert "daily_forecasts" in r.context
