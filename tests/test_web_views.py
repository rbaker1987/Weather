"""Tests for Django web interface views."""

from decimal import Decimal
from datetime import datetime, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from weather.models import DailyForecast, Location, WeatherAlert


@pytest.mark.django_db
class TestDashboardView:
    def test_dashboard_renders_with_locations_and_forecasts(self, client):
        session = client.session
        # Create locations
        loc1 = Location.objects.create(name="Home City", latitude=Decimal("30.0"), longitude=Decimal("-97.0"), is_current_location=True)
        loc2 = Location.objects.create(name="Work City", latitude=Decimal("31.0"), longitude=Decimal("-98.0"))
        session['location_ids'] = [str(loc1.id), str(loc2.id)]
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
            )

        resp = client.get(reverse('weather:dashboard'))
        assert resp.status_code == 200
        assert 'favorite_location' in resp.context
        assert resp.context['favorite_location'].id == loc1.id
        # 3 grouped days
        assert len(resp.context['daily_forecasts']) >= 1


@pytest.mark.django_db
class TestAlertListView:
    def test_alert_list_filters_by_session_and_counts(self, client):
        session = client.session
        loc1 = Location.objects.create(name="A")
        loc2 = Location.objects.create(name="B")
        session['location_ids'] = [str(loc1.id)]
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

        resp = client.get(reverse('weather:alert-list'))
        assert resp.status_code == 200
        alerts = list(resp.context['alerts'])
        # Only loc1 alerts should be present due to session filter
        assert all(a.location_id == loc1.id for a in alerts)
        assert resp.context['severe_extreme_count'] == 1
        assert resp.context['moderate_count'] == 1


@pytest.mark.django_db
class TestForecastListView:
    def test_forecast_list_groups_by_date_and_location(self, client, monkeypatch):
        session = client.session
        loc1 = Location.objects.create(name="A", is_enabled=True)
        loc2 = Location.objects.create(name="B", is_enabled=True)
        session['location_ids'] = [str(loc1.id), str(loc2.id)]
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
        resp = client.get(reverse('weather:forecast-list'))
        assert resp.status_code == 200
        assert 'grouped_by_date' in resp.context
        grouped = resp.context['grouped_by_date']
        assert len(grouped) >= 1
        # Each date entry should have both locations
        assert len(grouped[0]['locations']) == 2
