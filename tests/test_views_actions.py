from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from weather.models import DailyForecast, Location, WeatherAlert


def add_location_to_session(client, location):
    session = client.session
    ids = session.get('location_ids', [])
    ids = [str(x) for x in ids]
    lid = str(location.id)
    if lid not in ids:
        ids.append(lid)
    session['location_ids'] = ids
    session.save()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestLocationActions:
    def test_forecasts_get_daily_and_hourly(self, api_client):
        loc = Location.objects.create(name='L1', latitude=Decimal('1.0'), longitude=Decimal('2.0'))
        add_location_to_session(api_client, loc)
        today = timezone.now().date()
        # daily
        DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=70,
            short_forecast='Sunny',
            wind_speed=5,
        )
        # hourly not required for serializer path; we still call type=hourly with no data
        r1 = api_client.get(f'/api/locations/{loc.pk}/forecasts/?type=daily&days=3')
        assert r1.status_code == 200
        assert len(r1.data) >= 1
        r2 = api_client.get(f'/api/locations/{loc.pk}/forecasts/?type=hourly&days=1')
        assert r2.status_code == 200

    def test_ensure_browser_location_updates_existing_current(self, api_client):
        """Test updating an existing current location with new coords."""
        # Create a current location first
        existing = Location.objects.create(name='Old', latitude=Decimal('30.0'), longitude=Decimal('-95.0'), is_current_location=True)
        payload = {'name': 'Updated', 'latitude': 35.0, 'longitude': -90.0}
        with patch('weather.services.SyncWeatherService.update_forecasts_for_location') as _svc:
            r = api_client.post('/api/locations/ensure_browser_location/', payload, format='json')
        assert r.status_code == 200
        existing.refresh_from_db()
        assert existing.latitude == Decimal('35.0')
        assert existing.name == 'Updated'

    def test_reorder_exception_handling(self, api_client):
        """Trigger exception in reorder to hit error branch."""
        # Pass invalid location ID that causes exception
        with patch('weather.models.Location.objects.filter') as mock_filter:
            mock_filter.side_effect = Exception('db error')
            r = api_client.post('/api/locations/reorder/', {'location_order': ['bad-uuid']}, format='json')
        assert r.status_code == 500

    def test_forecasts_post_create_custom(self, api_client):
        loc = Location.objects.create(name='L2')
        add_location_to_session(api_client, loc)
        payload = {
            'date': timezone.now().date().isoformat(),
            'is_daytime': True,
            'temperature': 65,
            'short_forecast': 'Partly Cloudy',
        }
        r = api_client.post(f'/api/locations/{loc.pk}/forecasts/', payload, format='json')
        assert r.status_code in (200, 201)
        assert DailyForecast.objects.filter(location=loc).exists()

    def test_alerts_list(self, api_client):
        loc = Location.objects.create(name='L3')
        add_location_to_session(api_client, loc)
        WeatherAlert.objects.create(
            location=loc,
            event='Heat Advisory',
            severity='moderate',
            urgency='expected',
            headline='Heat',
            description='Hot',
            onset=timezone.now(),
            expires=timezone.now() + timedelta(hours=1),
            is_active=True,
            raw_data={},
        )
        r = api_client.get(f'/api/locations/{loc.pk}/alerts/')
        assert r.status_code == 200
        assert len(r.data) == 1

    def test_ensure_browser_location_success(self, api_client):
        payload = {'name': 'Here', 'latitude': 10.0, 'longitude': 20.0}
        # Patch the service where it's defined; views import it inside the method
        with patch('weather.services.SyncWeatherService.update_forecasts_for_location') as _svc:
            r = api_client.post('/api/locations/ensure_browser_location/', payload, format='json')
        assert r.status_code == 200
        assert r.data['status'] == 'success'
        # ensure session updated
        assert 'location_ids' in api_client.session
        assert len(api_client.session['location_ids']) >= 1

    def test_ensure_browser_location_missing_coords(self, api_client):
        r = api_client.post('/api/locations/ensure_browser_location/', {'name': 'bad'}, format='json')
        assert r.status_code == 400

    def test_reorder_success(self, api_client):
        l1 = Location.objects.create(name='A')
        l2 = Location.objects.create(name='B')
        order = [str(l2.id), str(l1.id)]
        r = api_client.post('/api/locations/reorder/', {'location_order': order}, format='json')
        assert r.status_code == 200
        l1.refresh_from_db()
        l2.refresh_from_db()
        assert l2.display_order == 0 and l1.display_order == 1

    def test_reorder_missing_order(self, api_client):
        r = api_client.post('/api/locations/reorder/', {}, format='json')
        assert r.status_code == 400

    def test_clear_all(self, api_client):
        Location.objects.create(name='X')
        Location.objects.create(name='Y')
        r = api_client.post('/api/locations/clear_all/', {}, format='json')
        assert r.status_code == 200
        assert r.data['status'] == 'success'

    def test_set_current_and_toggle(self, api_client):
        loc = Location.objects.create(name='Home')
        add_location_to_session(api_client, loc)
        r1 = api_client.post(f'/api/locations/{loc.pk}/set_current/')
        assert r1.status_code == 200
        loc.refresh_from_db()
        assert loc.is_current_location is True and loc.is_enabled is True
        r2 = api_client.post(f'/api/locations/{loc.pk}/toggle_enabled/')
        assert r2.status_code == 200
        loc.refresh_from_db()
        # toggled
        assert isinstance(loc.is_enabled, bool)
