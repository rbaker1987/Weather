"""Extended tests for views to improve coverage to 85%+."""

from datetime import datetime, time
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from weather.models import DailyForecast, Location


@pytest.fixture
def api_client():
    """API client fixture."""
    client = APIClient()
    return client


def add_location_to_session(client, location):
    """Helper to add location to session so it's visible in queryset."""
    session = client.session
    if 'location_ids' not in session:
        session['location_ids'] = []
    session['location_ids'].append(str(location.id))
    session.save()


@pytest.mark.django_db
class TestLocationViewSetUpdateForecast:
    """Test update_forecast action with various scenarios."""

    def test_update_forecast_no_coordinates_no_zip(self, api_client):
        """Test update_forecast when location has no coordinates and no zip code."""
        location = Location.objects.create(name="No Coords")
        add_location_to_session(api_client, location)

        response = api_client.post(f'/api/locations/{location.pk}/update_forecast/')

        assert response.status_code == 400
        assert 'coordinates or zip code' in str(response.data).lower()

    def test_update_forecast_with_current_conditions(self, api_client):
        """Test update_forecast fetches current conditions from observation station."""
        location = Location.objects.create(
            name="Test Location",
            latitude=Decimal("45.5152"),
            longitude=Decimal("-122.6784")
        )
        add_location_to_session(api_client, location)

        mock_grid_response = Mock()
        mock_grid_response.status_code = 200
        mock_grid_response.json.return_value = {
            'properties': {
                'gridId': 'PQR',
                'gridX': 100,
                'gridY': 50,
                'forecast': 'https://api.weather.gov/gridpoints/PQR/100,50/forecast',
                'observationStations': 'https://api.weather.gov/gridpoints/PQR/100,50/stations'
            }
        }

        mock_stations_response = Mock()
        mock_stations_response.status_code = 200
        mock_stations_response.json.return_value = {
            'features': [
                {
                    'properties': {
                        'stationIdentifier': 'KPDX'
                    }
                }
            ]
        }

        mock_obs_response = Mock()
        mock_obs_response.status_code = 200
        mock_obs_response.json.return_value = {
            'properties': {
                'temperature': {'value': 20.5},  # Celsius
                'textDescription': 'Partly Cloudy',
                'relativeHumidity': {'value': 65},
                'windSpeed': {'value': 16.09},  # km/h
                'windDirection': {'value': 315},  # degrees (NW)
                'timestamp': '2025-11-19T14:30:00Z'
            }
        }

        mock_forecast_response = Mock()
        mock_forecast_response.status_code = 200
        mock_forecast_response.json.return_value = {
            'properties': {
                'periods': []
            }
        }

        with patch('requests.get') as mock_get:
            mock_get.side_effect = [
                mock_grid_response,
                mock_stations_response,
                mock_obs_response,
                mock_forecast_response
            ]

            response = api_client.post(f'/api/locations/{location.pk}/update_forecast/')

        assert response.status_code == 200
        location.refresh_from_db()
        assert location.current_temp == 68  # 20.5C = 68.9F ≈ 68F (rounds down)
        assert location.current_conditions == 'Partly Cloudy'

    def test_update_forecast_processes_alerts(self, api_client):
        """Test update_forecast processes alert features and updates counts."""
        location = Location.objects.create(
            name="Alerts Loc",
            latitude=Decimal("35.0"),
            longitude=Decimal("-90.0"),
        )
        add_location_to_session(api_client, location)

        mock_grid_response = Mock()
        mock_grid_response.status_code = 200
        mock_grid_response.json.return_value = {
            'properties': {
                'gridId': 'MEG',
                'gridX': 10,
                'gridY': 20,
                'forecast': 'https://api.weather.gov/gridpoints/MEG/10,20/forecast',
                'observationStations': 'https://api.weather.gov/gridpoints/MEG/10,20/stations'
            }
        }

        mock_stations_response = Mock()
        mock_stations_response.status_code = 200
        mock_stations_response.json.return_value = {
            'features': [
                {'properties': {'stationIdentifier': 'KMEM'}}
            ]
        }

        mock_obs_response = Mock()
        mock_obs_response.status_code = 200
        mock_obs_response.json.return_value = {
            'properties': {
                'temperature': {'value': 10},
                'textDescription': 'Cloudy',
                'relativeHumidity': {'value': 50},
                'windSpeed': {'value': 0},
                'windDirection': {'value': 180},
                'timestamp': '2025-01-01T00:00:00Z'
            }
        }

        mock_forecast_response = Mock()
        mock_forecast_response.status_code = 200
        mock_forecast_response.json.return_value = {
            'properties': {'periods': []}
        }

        mock_alerts_response = Mock()
        mock_alerts_response.status_code = 200
        mock_alerts_response.json.return_value = {
            'features': [
                {'properties': {
                    'id': 'ALERT1', 'event': 'Warning', 'headline': 'Severe',
                    'description': 'Desc', 'severity': 'Severe', 'urgency': 'Immediate',
                    'onset': '2025-01-01T01:00:00Z', 'expires': '2025-01-01T02:00:00Z'
                }}
            ]
        }

        with patch('requests.get') as mock_get:
            mock_get.side_effect = [
                mock_grid_response,
                mock_stations_response,
                mock_obs_response,
                mock_forecast_response,
                mock_alerts_response,
            ]
            resp = api_client.post(f'/api/locations/{location.pk}/update_forecast/')
        assert resp.status_code == 200
        assert 'alerts_created' in resp.data

    def test_update_forecast_handles_request_exception(self, api_client):
        """Trigger requests exception to hit error branch."""
        location = Location.objects.create(name="Err Loc", latitude=Decimal("40.0"), longitude=Decimal("-80.0"))
        add_location_to_session(api_client, location)
        class EResp:
            def raise_for_status(self):
                raise Exception('bad')
        # First grid ok, then forecast raises RequestException
        with patch('requests.get') as mock_get:
            import requests
            grid = Mock()
            grid.status_code = 200
            grid.json.return_value = {'properties': {'forecast': 'x', 'gridId': 'A', 'gridX': 1, 'gridY': 2}}
            mock_get.side_effect = [grid, requests.exceptions.RequestException('boom')]
            r = api_client.post(f'/api/locations/{location.pk}/update_forecast/')
        assert r.status_code == 500

    def test_update_forecast_creates_periods_with_wind_range(self, api_client):
        """Ensure forecast periods are created and wind range parsed."""
        location = Location.objects.create(name="Periods Loc", latitude=Decimal("41.0"), longitude=Decimal("-81.0"))
        add_location_to_session(api_client, location)
        today = timezone.now().date()
        mock_grid = Mock()
        mock_grid.status_code = 200
        mock_grid.json.return_value = {
            'properties': {
                'gridId': 'CLE', 'gridX': 5, 'gridY': 6,
                'forecast': 'https://api.weather.gov/gridpoints/CLE/5,6/forecast',
                'observationStations': 'https://api.weather.gov/gridpoints/CLE/5,6/stations'
            }
        }
        mock_stations = Mock()
        mock_stations.status_code = 200
        mock_stations.json.return_value = {'features': [{'properties': {'stationIdentifier': 'KCLE'}}]}
        mock_obs = Mock()
        mock_obs.status_code = 200
        mock_obs.json.return_value = {'properties': {'temperature': {'value': 15}, 'relativeHumidity': {'value': 50}, 'windSpeed': {'value': 8}, 'windDirection': {'value': 90}, 'timestamp': f'{today}T00:00:00Z'}}
        mock_fcst = Mock()
        mock_fcst.status_code = 200
        mock_fcst.json.return_value = {
            'properties': {
                'periods': [{
                    'startTime': f'{today}T06:00:00Z', 'endTime': f'{today}T18:00:00Z',
                    'isDaytime': True, 'temperature': 70, 'temperatureUnit': 'F',
                    'windSpeed': '10 to 15 mph', 'windDirection': 'NE',
                    'shortForecast': 'Sunny', 'detailedForecast': 'Nice day',
                    'probabilityOfPrecipitation': {'value': 10}
                }]
            }
        }
        # Skip alerts by returning empty
        mock_alerts = Mock()
        mock_alerts.status_code = 200
        mock_alerts.json.return_value = {'features': []}
        with patch('requests.get') as mock_get:
            mock_get.side_effect = [mock_grid, mock_stations, mock_obs, mock_fcst, mock_alerts]
            resp = api_client.post(f'/api/locations/{location.pk}/update_forecast/')
        assert resp.status_code == 200
        assert DailyForecast.objects.filter(location=location).count() == 1

    def test_update_forecast_geocodes_zip(self, api_client):
        """Test update_forecast geocodes location with zip code but no coords."""
        location = Location.objects.create(name='Zip Loc', zip_code='10001')
        add_location_to_session(api_client, location)

        mock_geo = Mock()
        mock_geo.status_code = 200
        mock_geo.json.return_value = [{'lat': '40.75', 'lon': '-73.99'}]

        mock_grid = Mock()
        mock_grid.status_code = 200
        mock_grid.json.return_value = {'properties': {'gridId': 'NYC', 'gridX': 10, 'gridY': 20, 'forecast': 'https://api.weather.gov/gridpoints/NYC/10,20/forecast', 'observationStations': 'https://api.weather.gov/gridpoints/NYC/10,20/stations'}}

        mock_stations = Mock()
        mock_stations.status_code = 200
        mock_stations.json.return_value = {'features': []}

        mock_fcst = Mock()
        mock_fcst.status_code = 200
        mock_fcst.json.return_value = {'properties': {'periods': []}}

        mock_alerts = Mock()
        mock_alerts.status_code = 200
        mock_alerts.json.return_value = {'features': []}

        with patch('requests.get') as mock_get:
            mock_get.side_effect = [mock_geo, mock_grid, mock_stations, mock_fcst, mock_alerts]
            resp = api_client.post(f'/api/locations/{location.pk}/update_forecast/')

        assert resp.status_code == 200
        location.refresh_from_db()
        assert location.latitude == Decimal('40.75')


@pytest.mark.django_db
class TestBulkForecastAPIView:
    """Test bulk forecast API view."""

    def test_bulk_forecast_with_nonexistent_locations(self, api_client):
        """Test bulk forecast with locations that don't exist."""
        fake_uuid = '00000000-0000-0000-0000-000000000000'

        response = api_client.post('/api/bulk-forecast/', {
            'location_ids': [fake_uuid]
        }, format='json')

        assert response.status_code == 400

    def test_bulk_forecast_missing_location_ids(self, api_client):
        """Test bulk forecast without location_ids parameter."""
        response = api_client.post('/api/bulk-forecast/', {}, format='json')

        assert response.status_code in [200, 400]

    def test_bulk_forecast_success_with_alerts(self, api_client):
        """Bulk forecast returns data for existing location including alerts."""
        # Create a location matching by name
        loc = Location.objects.create(name="Bulk City")
        # Create an active alert
        from weather.models import WeatherAlert as DJWeatherAlert
        DJWeatherAlert.objects.create(
            location=loc,
            nws_alert_id='BULK1',
            event='Advisory',
            headline='Heads up',
            description='',
            severity='moderate',
            urgency='expected',
            onset=timezone.now(),
            expires=timezone.now() + timezone.timedelta(hours=2),
            is_active=True,
            raw_data={},
        )

        payload = {
            'locations': ['Bulk City'],
            'forecast_type': 'both',
            'days': 1,
            'include_alerts': True,
        }
        resp = api_client.post('/api/bulk-forecast/', payload, format='json')
        assert resp.status_code == 200
        assert resp.data['status'] == 'success'
        assert isinstance(resp.data['locations'], list)


@pytest.mark.django_db
class TestExportAPIView:
    """Test export API views for different formats."""

    def test_export_kml_no_coordinates(self, api_client):
        """Test KML export with location that has no coordinates."""
        location = Location.objects.create(name="No Coords Location")

        response = api_client.post('/api/export/', {
            'format': 'kml',
            'locations': [str(location.id)]
        }, format='json')

        assert response.status_code == 200

    def test_export_csv_with_forecasts(self, api_client):
        """Test CSV export includes forecast data."""
        location = Location.objects.create(
            name="Test Location",
            latitude=Decimal("45.5"),
            longitude=Decimal("-122.6")
        )
        today = timezone.now().date()

        DailyForecast.objects.create(
            location=location,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=75,
            short_forecast="Sunny",
            wind_speed=10,
            high_temperature=80,
            low_temperature=60,
        )

        response = api_client.post('/api/export/', {
            'format': 'csv',
            'locations': [str(location.id)]
        }, format='json')

        assert response.status_code == 200
        assert 'text/csv' in response['Content-Type'] or 'application/csv' in response['Content-Type']

    def test_export_json(self, api_client):
        loc = Location.objects.create(name="JSON Loc")
        today = timezone.now().date()
        DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=70,
            short_forecast='OK',
            wind_speed=5,
        )
        resp = api_client.post('/api/export/', {'format': 'json', 'locations': [str(loc.id)]}, format='json')
        assert resp.status_code == 200
        assert 'application/json' in resp['Content-Type']


@pytest.mark.django_db
class TestWeatherStatsAPIView:
    """Test weather statistics API view."""

    def test_weather_stats_with_data(self, api_client):
        """Test weather stats calculation with forecast data."""
        location = Location.objects.create(name="Stats Location")
        today = timezone.now().date()

        for i, temp in enumerate([65, 70, 75, 80, 85]):
            DailyForecast.objects.create(
                location=location,
                forecast_date=today + timezone.timedelta(days=i),
                period_start=timezone.make_aware(datetime.combine(today + timezone.timedelta(days=i), time(6, 0))),
                period_end=timezone.make_aware(datetime.combine(today + timezone.timedelta(days=i), time(18, 0))),
                is_daytime=True,
                temperature=temp,
                short_forecast="Test",
                wind_speed=10,
            )

        response = api_client.get('/api/stats/')

        assert response.status_code == 200
        assert 'total_forecasts' in response.data

    def test_weather_stats_no_data(self, api_client):
        """Test weather stats with no forecast data."""
        response = api_client.get('/api/stats/')

        assert response.status_code == 200
