"""Django REST Framework views for weather API."""

import json
import logging
from datetime import datetime, time, timedelta

from django.db.models import Avg, Case, Count, IntegerField, Q, When
from django.http import HttpResponse
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    DailyForecast,
    ForecastRequest,
    HourlyForecast,
    Location,
    WeatherAlert,
)
from .serializers import (
    BulkForecastRequestSerializer,
    DailyForecastSerializer,
    HourlyForecastSerializer,
    LocationSerializer,
    WeatherAlertSerializer,
)
from .utils.apparent_temperature import calculate_apparent_temperature


logger = logging.getLogger('weather')


def fetch_current_conditions(location):
    """Helper function to fetch and update current conditions for a location."""
    if not location.latitude or not location.longitude:
        return False

    try:
        from datetime import datetime

        import requests

        headers = {'User-Agent': '(Weather App, contact@example.com)'}

        # Get grid point data
        grid_url = f'https://api.weather.gov/points/{location.latitude},{location.longitude}'
        grid_response = requests.get(grid_url, headers=headers, timeout=10)
        grid_response.raise_for_status()
        grid_data = grid_response.json()

        properties = grid_data.get('properties', {})
        observation_stations_url = properties.get('observationStations')

        if not observation_stations_url:
            return False

        # Get observation stations
        stations_response = requests.get(observation_stations_url, headers=headers, timeout=10)
        stations_response.raise_for_status()
        stations_data = stations_response.json()

        stations = stations_data.get('features', [])
        if not stations:
            return False

        station_id = stations[0].get('properties', {}).get('stationIdentifier')
        if not station_id:
            return False

        # Get latest observation
        obs_url = f'https://api.weather.gov/stations/{station_id}/observations/latest'
        obs_response = requests.get(obs_url, headers=headers, timeout=10)
        obs_response.raise_for_status()
        obs_data = obs_response.json()

        obs_props = obs_data.get('properties', {})

        # Extract and update current conditions
        temp_c = obs_props.get('temperature', {}).get('value')
        if temp_c:
            location.current_temp = int(temp_c * 9/5 + 32)

        location.current_conditions = obs_props.get('textDescription', '')

        humidity = obs_props.get('relativeHumidity', {}).get('value')
        if humidity:
            location.current_humidity = int(humidity)

        wind_speed_kmh = obs_props.get('windSpeed', {}).get('value')
        if wind_speed_kmh is not None:
            try:
                location.current_wind_speed = int(wind_speed_kmh * 0.621371)
            except (ValueError, TypeError):
                location.current_wind_speed = 0
        else:
            location.current_wind_speed = 0

        # Wind gust
        wind_gust_kmh = obs_props.get('windGust', {}).get('value')
        if wind_gust_kmh is not None:
            try:
                location.current_wind_gust = int(wind_gust_kmh * 0.621371)
            except (ValueError, TypeError):
                location.current_wind_gust = None
        else:
            location.current_wind_gust = None

        wind_dir_deg = obs_props.get('windDirection', {}).get('value')
        if wind_dir_deg is not None:
            try:
                deg = float(wind_dir_deg)
                directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
                location.current_wind_direction = directions[int((deg + 22.5) / 45) % 8]
            except (ValueError, TypeError):
                location.current_wind_direction = ''
        else:
            location.current_wind_direction = ''

        # Calculate apparent temperature
        if location.current_temp is not None:
            dew_point_c = obs_props.get('dewpoint', {}).get('value')
            location.current_apparent_temp = calculate_apparent_temperature(
                temp_f=location.current_temp,
                humidity_pct=location.current_humidity,
                wind_speed_mph=location.current_wind_speed or 0,
                dew_point_c=dew_point_c
            )

        timestamp = obs_props.get('timestamp')
        if timestamp:
            location.last_observation_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

        location.save()
        return True

    except Exception as e:
        logger.warning(f"Could not fetch current conditions for {location.name}: {str(e)}")
        return False


class LocationViewSet(viewsets.ModelViewSet):
    """API ViewSet for managing locations."""

    queryset = Location.objects.filter(is_active=True)
    serializer_class = LocationSerializer
    permission_classes = [permissions.AllowAny]
    search_fields = ['name', 'zip_code']
    ordering_fields = ['name', 'created_at', 'last_forecast_update']
    ordering = ['name']

    def get_queryset(self):
        """Filter locations by session."""
        queryset = super().get_queryset()

        # Only show locations in session
        location_ids = self.request.session.get('location_ids', [])
        queryset = queryset.filter(id__in=location_ids)

        return queryset.annotate(
            forecast_count=Count('forecasts')
        )

    def perform_create(self, serializer):
        """Save location and add to session."""
        location = serializer.save()

        # Save location ID in session (convert UUID to string)
        if 'location_ids' not in self.request.session:
            self.request.session['location_ids'] = []
        self.request.session['location_ids'].append(str(location.id))
        self.request.session.modified = True

        # If location doesn't have coordinates, try to geocode
        if not location.latitude or not location.longitude:
            try:
                import requests
                headers = {'User-Agent': 'WeatherApp/1.0'}

                # Try zip code first if available
                if location.zip_code:
                    geocode_url = f'https://nominatim.openstreetmap.org/search?postalcode={location.zip_code}&country=US&format=json&limit=1'
                else:
                    # Otherwise geocode the name
                    geocode_url = f'https://nominatim.openstreetmap.org/search?q={location.name}&format=json&limit=1'

                geo_response = requests.get(geocode_url, headers=headers, timeout=10)
                geo_response.raise_for_status()
                geo_data = geo_response.json()

                if geo_data and len(geo_data) > 0:
                    location.latitude = float(geo_data[0]['lat'])
                    location.longitude = float(geo_data[0]['lon'])
                    location.save()
            except Exception as e:
                # Log error but don't fail the creation
                logger.warning(f"Geocoding error: {str(e)}")

        # Automatically fetch current conditions after creating location
        if location.latitude and location.longitude:
            try:
                fetch_current_conditions(location)
            except Exception as e:
                logger.warning(f"Could not fetch initial conditions for {location.name}: {str(e)}")

    @action(detail=True, methods=['get', 'post'])
    def forecasts(self, request, pk=None):
        """Get forecasts for a specific location or create a custom forecast."""
        location = self.get_object()

        if request.method == 'POST':
            # Create a custom forecast
            data = request.data.copy()
            data['location'] = location.id

            # Parse the date and period
            forecast_date = data.get('date')
            is_daytime = data.get('is_daytime', True)

            if forecast_date:
                data['forecast_date'] = forecast_date

                # Calculate period_start and period_end
                forecast_date_obj = datetime.strptime(forecast_date, '%Y-%m-%d').date()
                if is_daytime:
                    # Day period: 6 AM to 6 PM
                    period_start = datetime.combine(forecast_date_obj, time(6, 0))
                    period_end = datetime.combine(forecast_date_obj, time(18, 0))
                else:
                    # Night period: 6 PM to 6 AM next day
                    period_start = datetime.combine(forecast_date_obj, time(18, 0))
                    period_end = datetime.combine(forecast_date_obj + timedelta(days=1), time(6, 0))

                data['period_start'] = period_start.isoformat()
                data['period_end'] = period_end.isoformat()

                # Set default values for required fields if not provided
                if 'wind_speed' not in data:
                    data['wind_speed'] = 0
                if 'wind_direction' not in data:
                    data['wind_direction'] = ''

            serializer = DailyForecastSerializer(data=data)
            if serializer.is_valid():
                serializer.save(location=location)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # GET request - return forecasts
        forecast_type = request.query_params.get('type', 'daily')
        days = int(request.query_params.get('days', 5))

        end_date = timezone.now().date() + timedelta(days=days)

        if forecast_type == 'hourly':
            forecasts = HourlyForecast.objects.filter(
                location=location,
                forecast_date__lte=end_date
            ).order_by('period_start')
            serializer = HourlyForecastSerializer(forecasts, many=True)
        else:
            forecasts = DailyForecast.objects.filter(
                location=location,
                forecast_date__lte=end_date
            ).order_by('forecast_date')
            serializer = DailyForecastSerializer(forecasts, many=True)

        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def alerts(self, request, pk=None):
        """Get active alerts for a specific location."""
        location = self.get_object()
        alerts = WeatherAlert.objects.filter(
            location=location,
            is_active=True,
            expires__gt=timezone.now()
        ).order_by('-severity', '-onset')

        serializer = WeatherAlertSerializer(alerts, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def ensure_browser_location(self, request):
        """Create or update a 'current' location from browser coordinates.
        Payload: { name: str, latitude: float, longitude: float }
        Ensures the location is enabled, marked current, and added to session.
        Returns the location id.
        """
        try:
            data = request.data or {}
            name = data.get('name') or 'My Location'
            lat = data.get('latitude')
            lon = data.get('longitude')
            if lat is None or lon is None:
                return Response({'status': 'error', 'message': 'latitude and longitude are required'}, status=status.HTTP_400_BAD_REQUEST)

            # If a current location exists, update its coordinates and name
            location = Location.objects.filter(is_current_location=True).first()
            if location is None:
                location = Location.objects.create(
                    name=name,
                    latitude=lat,
                    longitude=lon,
                    is_active=True,
                    is_enabled=True,
                    is_current_location=True,
                )
            else:
                location.name = name or location.name
                location.latitude = lat
                location.longitude = lon
                location.is_active = True
                location.is_enabled = True
                location.is_current_location = True
                location.save(update_fields=['name','latitude','longitude','is_active','is_enabled','is_current_location'])

            # Ensure in session (store as strings)
            session_ids = request.session.get('location_ids', [])
            session_ids_str = [str(x) for x in session_ids]
            loc_id_str = str(location.id)
            if loc_id_str not in session_ids_str:
                session_ids_str.append(loc_id_str)
                request.session['location_ids'] = session_ids_str
                request.session.modified = True

            # Kick off a forecast refresh (best-effort)
            try:
                from .services import SyncWeatherService
                SyncWeatherService.update_forecasts_for_location(location)
            except Exception:
                _refresh_forecasts_for_location(location)

            return Response({'status': 'success', 'location_id': str(location.id)})
        except Exception as e:
            logger.exception('ensure_browser_location failed: %s', e)
            return Response({'status': 'error', 'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def update_forecast(self, request, pk=None):
        """Manually trigger forecast update for a location."""
        location = self.get_object()

        # Check if location has coordinates
        if not location.latitude or not location.longitude:
            # Try to get coordinates from zip code
            if location.zip_code:
                try:
                    import requests
                    # Use OpenStreetMap Nominatim (free, no API key required)
                    # Must include User-Agent header per usage policy
                    headers = {'User-Agent': 'WeatherApp/1.0'}
                    geocode_url = f'https://nominatim.openstreetmap.org/search?postalcode={location.zip_code}&country=US&format=json&limit=1'
                    geo_response = requests.get(geocode_url, headers=headers, timeout=10)
                    geo_response.raise_for_status()
                    geo_data = geo_response.json()

                    if geo_data and len(geo_data) > 0:
                        location.latitude = float(geo_data[0]['lat'])
                        location.longitude = float(geo_data[0]['lon'])
                        location.save()
                    else:
                        return Response({
                            'status': 'error',
                            'message': f'Could not geocode zip code {location.zip_code}. Please manually add coordinates.'
                        }, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    return Response({
                        'status': 'error',
                        'message': f'Error geocoding zip code: {str(e)}. Please manually add coordinates.'
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    'status': 'error',
                    'message': 'Location does not have coordinates or zip code. Please update the location.'
                }, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Fetch forecast data from NWS API
            import requests

            # Get grid point data
            grid_url = f'https://api.weather.gov/points/{location.latitude},{location.longitude}'
            headers = {'User-Agent': '(Weather App, contact@example.com)'}

            grid_response = requests.get(grid_url, headers=headers, timeout=10)
            grid_response.raise_for_status()
            grid_data = grid_response.json()

            # Update NWS grid info
            properties = grid_data.get('properties', {})
            location.nws_office = properties.get('gridId', '')
            location.grid_x = properties.get('gridX')
            location.grid_y = properties.get('gridY')

            # Fetch current conditions from observation station
            try:
                observation_stations_url = properties.get('observationStations')
                if observation_stations_url:
                    stations_response = requests.get(observation_stations_url, headers=headers, timeout=10)
                    stations_response.raise_for_status()
                    stations_data = stations_response.json()

                    # Get first station
                    stations = stations_data.get('features', [])
                    if stations:
                        station_id = stations[0].get('properties', {}).get('stationIdentifier')
                        if station_id:
                            # Get latest observation
                            obs_url = f'https://api.weather.gov/stations/{station_id}/observations/latest'
                            obs_response = requests.get(obs_url, headers=headers, timeout=10)
                            obs_response.raise_for_status()
                            obs_data = obs_response.json()

                            obs_props = obs_data.get('properties', {})

                            # Extract current conditions
                            temp_c = obs_props.get('temperature', {}).get('value')
                            if temp_c:
                                # Convert Celsius to Fahrenheit
                                location.current_temp = int(temp_c * 9/5 + 32)

                            location.current_conditions = obs_props.get('textDescription', '')

                            humidity = obs_props.get('relativeHumidity', {}).get('value')
                            if humidity:
                                location.current_humidity = int(humidity)

                            wind_speed_kmh = obs_props.get('windSpeed', {}).get('value')
                            if wind_speed_kmh is not None:
                                try:
                                    # Wind speed from NWS is in km/h, convert to mph
                                    location.current_wind_speed = int(wind_speed_kmh * 0.621371)
                                except (ValueError, TypeError):
                                    location.current_wind_speed = 0
                            else:
                                location.current_wind_speed = 0

                            # Wind gust
                            wind_gust_kmh = obs_props.get('windGust', {}).get('value')
                            if wind_gust_kmh is not None:
                                try:
                                    location.current_wind_gust = int(wind_gust_kmh * 0.621371)
                                except (ValueError, TypeError):
                                    location.current_wind_gust = None
                            else:
                                location.current_wind_gust = None

                            wind_dir_deg = obs_props.get('windDirection', {}).get('value')
                            if wind_dir_deg is not None:
                                # Convert degrees to cardinal direction
                                try:
                                    deg = float(wind_dir_deg)
                                    directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
                                    location.current_wind_direction = directions[int((deg + 22.5) / 45) % 8]
                                except (ValueError, TypeError):
                                    location.current_wind_direction = ''
                            else:
                                location.current_wind_direction = ''

                            # Calculate apparent temperature
                            if location.current_temp is not None:
                                dew_point_c = obs_props.get('dewpoint', {}).get('value')
                                location.current_apparent_temp = calculate_apparent_temperature(
                                    temp_f=location.current_temp,
                                    humidity_pct=location.current_humidity,
                                    wind_speed_mph=location.current_wind_speed or 0,
                                    dew_point_c=dew_point_c
                                )

                            timestamp = obs_props.get('timestamp')
                            if timestamp:
                                location.last_observation_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            
                            # Save current conditions including apparent temperature
                            location.save()
            except Exception as e:
                print(f"Warning: Could not fetch current conditions: {str(e)}")

            # Get forecast URL
            forecast_url = properties.get('forecast')
            if not forecast_url:
                raise Exception('No forecast URL available')

            # Fetch forecast data
            forecast_response = requests.get(forecast_url, headers=headers, timeout=10)
            forecast_response.raise_for_status()
            forecast_data = forecast_response.json()

            # Parse and save forecast periods
            periods = forecast_data.get('properties', {}).get('periods', [])

            # Clear old forecasts
            DailyForecast.objects.filter(location=location).delete()

            # Helper function to parse wind speed
            def parse_wind_speed(wind_speed_str):
                """Extract numeric wind speed from string like '10 to 15 mph' or '10 mph'."""
                if not wind_speed_str:
                    return 0
                import re
                # Extract all numbers from the string
                numbers = re.findall(r'\d+', str(wind_speed_str))
                if numbers:
                    # If range like "10 to 15", take the average
                    if len(numbers) > 1:
                        return int((int(numbers[0]) + int(numbers[1])) / 2)
                    return int(numbers[0])
                return 0

            # Create new forecasts
            for period in periods[:14]:  # Get up to 14 periods (7 days)
                DailyForecast.objects.create(
                    location=location,
                    forecast_date=datetime.fromisoformat(period['startTime'].replace('Z', '+00:00')).date(),
                    period_start=datetime.fromisoformat(period['startTime'].replace('Z', '+00:00')),
                    period_end=datetime.fromisoformat(period['endTime'].replace('Z', '+00:00')),
                    is_daytime=period.get('isDaytime', True),
                    temperature=period.get('temperature'),
                    temperature_unit=period.get('temperatureUnit', 'F'),
                    wind_speed=parse_wind_speed(period.get('windSpeed', '')),
                    wind_direction=period.get('windDirection', ''),
                    short_forecast=period.get('shortForecast', ''),
                    detailed_forecast=period.get('detailedForecast', ''),
                    precipitation_probability=period.get('probabilityOfPrecipitation', {}).get('value'),
                )

            # Fetch weather alerts
            alerts_created = 0
            alerts_updated = 0
            try:
                # Get active alerts for this location
                alerts_url = f'https://api.weather.gov/alerts/active?point={location.latitude},{location.longitude}'
                alerts_response = requests.get(alerts_url, headers=headers, timeout=10)
                alerts_response.raise_for_status()
                alerts_data = alerts_response.json()

                # Deactivate old alerts for this location
                from weather.models import WeatherAlert
                WeatherAlert.objects.filter(location=location).update(is_active=False)

                # Process each alert
                features = alerts_data.get('features', [])
                for feature in features:
                    props = feature.get('properties', {})
                    nws_id = props.get('id')

                    if not nws_id:
                        continue

                    # Parse dates
                    onset = props.get('onset')
                    expires = props.get('expires')

                    if onset:
                        onset = datetime.fromisoformat(onset.replace('Z', '+00:00'))
                    if expires:
                        expires = datetime.fromisoformat(expires.replace('Z', '+00:00'))

                    # Create or update alert
                    alert, created = WeatherAlert.objects.update_or_create(
                        nws_alert_id=nws_id,
                        defaults={
                            'location': location,
                            'event': props.get('event', 'Unknown'),
                            'headline': props.get('headline', ''),
                            'description': props.get('description', ''),
                            'severity': props.get('severity', 'unknown').lower(),
                            'urgency': props.get('urgency', 'unknown').lower(),
                            'onset': onset,
                            'expires': expires,
                            'is_active': True,
                            'raw_data': props,
                        }
                    )

                    if created:
                        alerts_created += 1
                    else:
                        alerts_updated += 1

            except requests.exceptions.RequestException as e:
                # Don't fail the entire update if alerts fail
                print(f"Warning: Failed to fetch alerts: {str(e)}")
            except Exception as e:
                print(f"Warning: Error processing alerts: {str(e)}")

            # Update location
            location.last_forecast_update = timezone.now()
            location.save()

            return Response({
                'status': 'success',
                'message': f'Forecast updated for {location.name}',
                'last_update': location.last_forecast_update,
                'forecasts_created': len(periods[:14]),
                'alerts_created': alerts_created,
                'alerts_updated': alerts_updated
            })

        except requests.exceptions.RequestException as e:
            return Response({
                'status': 'error',
                'message': f'Failed to fetch forecast data: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({
                'status': 'error',
                'message': f'Error updating forecast: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """Reorder locations based on provided order."""
        location_order = request.data.get('location_order', [])

        if not location_order:
            return Response({
                'status': 'error',
                'message': 'No location order provided'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Update display_order for each location
            for index, location_id in enumerate(location_order):
                Location.objects.filter(id=location_id).update(display_order=index)

            return Response({
                'status': 'success',
                'message': 'Location order updated'
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'message': f'Error updating order: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def clear_all(self, request):
        """Delete all saved locations and their related data.
        Only affects persisted locations; the browser 'current location' card is not stored.
        """
        try:
            count = Location.objects.filter(is_active=True).count()
            Location.objects.filter(is_active=True).delete()
            return Response({
                'status': 'success',
                'deleted': count,
                'message': f'Removed {count} location(s)'
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'message': f'Error clearing locations: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Removed favorite support; reordering replaces this feature.

    @action(detail=True, methods=['post'])
    def set_current(self, request, pk=None):
        """Set this location as current/home location."""
        location = self.get_object()

        try:
            # Unset any existing current location
            Location.objects.filter(is_current_location=True).update(is_current_location=False)

            # Set this location as current and ensure it's enabled
            location.is_current_location = True
            location.is_enabled = True
            location.save(update_fields=['is_current_location', 'is_enabled'])

            # Ensure this location is tracked in session
            session_ids = request.session.get('location_ids', [])
            # Normalize all IDs to strings
            session_ids_str = [str(x) for x in session_ids]
            loc_id_str = str(location.id)
            if loc_id_str not in session_ids_str:
                session_ids_str.append(loc_id_str)
                request.session['location_ids'] = session_ids_str
                request.session.modified = True

            return Response({
                'status': 'success',
                'message': f'{location.display_name} set as current location'
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'message': f'Error setting current location: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def toggle_enabled(self, request, pk=None):
        """Toggle location enabled/disabled state."""
        location = self.get_object()

        try:
            # Toggle the is_enabled field
            location.is_enabled = not location.is_enabled
            location.save()

            return Response({
                'status': 'success',
                'is_enabled': location.is_enabled,
                'message': f'{location.display_name} {"enabled" if location.is_enabled else "disabled"}'
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'message': f'Error toggling location: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HourlyForecastViewSet(viewsets.ReadOnlyModelViewSet):
    """API ViewSet for hourly forecasts."""

    queryset = HourlyForecast.objects.all()
    serializer_class = HourlyForecastSerializer
    permission_classes = [permissions.AllowAny]
    filterset_fields = ['location', 'forecast_date']
    ordering = ['location', 'period_start']

    def get_queryset(self):
        """Filter forecasts by date range and location."""
        queryset = super().get_queryset()

        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            queryset = queryset.filter(forecast_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(forecast_date__lte=end_date)

        # Filter by location name or zip
        location_query = self.request.query_params.get('location')
        if location_query:
            queryset = queryset.filter(
                Q(location__name__icontains=location_query) |
                Q(location__zip_code=location_query)
            )

        return queryset


class DailyForecastViewSet(viewsets.ReadOnlyModelViewSet):
    """API ViewSet for daily forecasts."""

    queryset = DailyForecast.objects.all()
    serializer_class = DailyForecastSerializer
    permission_classes = [permissions.AllowAny]
    filterset_fields = ['location', 'forecast_date']
    ordering = ['location', 'forecast_date']

    def get_queryset(self):
        """Filter forecasts by date range and location."""
        queryset = super().get_queryset()

        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            queryset = queryset.filter(forecast_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(forecast_date__lte=end_date)

        # Filter by location
        location_query = self.request.query_params.get('location')
        if location_query:
            queryset = queryset.filter(
                Q(location__name__icontains=location_query) |
                Q(location__zip_code=location_query)
            )

        return queryset


class WeatherAlertViewSet(viewsets.ReadOnlyModelViewSet):
    """API ViewSet for weather alerts."""

    queryset = WeatherAlert.objects.filter(is_active=True)
    serializer_class = WeatherAlertSerializer
    permission_classes = [permissions.AllowAny]
    filterset_fields = ['location', 'severity', 'urgency']
    ordering = ['-onset', '-created_at']

    def get_queryset(self):
        """Filter active alerts."""
        queryset = super().get_queryset()

        # Only show non-expired alerts by default
        show_expired = self.request.query_params.get('include_expired', 'false').lower() == 'true'
        if not show_expired:
            queryset = queryset.filter(expires__gt=timezone.now())

        # Filter by location
        location_query = self.request.query_params.get('location')
        if location_query:
            queryset = queryset.filter(
                Q(location__name__icontains=location_query) |
                Q(location__zip_code=location_query)
            )

        return queryset


class BulkForecastAPIView(APIView):
    """API view for bulk forecast requests."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """Process bulk forecast request."""
        serializer = BulkForecastRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data

        # Create forecast request record
        forecast_request = ForecastRequest.objects.create(
            session_key=request.session.session_key or '',
            request_type='bulk_forecast',
            status=ForecastRequest.RequestStatus.PENDING
        )

        try:
            # Process locations (this would integrate with your existing geocoding logic)
            locations_data = []
            for location_input in validated_data['locations']:
                # Try to find existing location
                location = Location.objects.filter(
                    Q(name__icontains=location_input) |
                    Q(zip_code=location_input)
                ).first()

                if location:
                    locations_data.append({
                        'location': LocationSerializer(location).data,
                        'forecasts': self._get_forecast_data(location, validated_data)
                    })
                else:
                    # Would create new location using your geocoding service
                    locations_data.append({
                        'error': f'Location not found: {location_input}'
                    })

            forecast_request.status = ForecastRequest.RequestStatus.SUCCESS
            forecast_request.save()

            return Response({
                'request_id': forecast_request.id,
                'status': 'success',
                'locations': locations_data
            })

        except Exception as e:
            forecast_request.status = ForecastRequest.RequestStatus.FAILED
            forecast_request.error_message = str(e)
            forecast_request.save()

            logger.error(f"Bulk forecast request failed: {e}")
            return Response({
                'error': 'Forecast request failed',
                'details': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _get_forecast_data(self, location, validated_data):
        """Get forecast data for a location."""
        forecast_type = validated_data['forecast_type']
        days = validated_data['days']
        end_date = timezone.now().date() + timedelta(days=days)

        result = {}

        if forecast_type in ['daily', 'both']:
            daily_forecasts = DailyForecast.objects.filter(
                location=location,
                forecast_date__lte=end_date
            ).order_by('forecast_date')
            result['daily'] = DailyForecastSerializer(daily_forecasts, many=True).data

        if forecast_type in ['hourly', 'both']:
            hourly_forecasts = HourlyForecast.objects.filter(
                location=location,
                forecast_date__lte=end_date
            ).order_by('period_start')
            result['hourly'] = HourlyForecastSerializer(hourly_forecasts, many=True).data

        if validated_data['include_alerts']:
            alerts = WeatherAlert.objects.filter(
                location=location,
                is_active=True,
                expires__gt=timezone.now()
            ).order_by('-severity')
            result['alerts'] = WeatherAlertSerializer(alerts, many=True).data

        return result


class WeatherStatsAPIView(APIView):
    """API view for weather statistics."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        """Get weather statistics."""
        stats = {
            'total_locations': Location.objects.filter(is_active=True).count(),
            'total_forecasts': DailyForecast.objects.count() + HourlyForecast.objects.count(),
            'active_alerts': WeatherAlert.objects.filter(
                is_active=True,
                expires__gt=timezone.now()
            ).count(),
            'recent_requests': ForecastRequest.objects.filter(
                created_at__gte=timezone.now() - timedelta(hours=24)
            ).count(),
        }

        # Temperature stats for last 7 days
        week_ago = timezone.now() - timedelta(days=7)
        recent_forecasts = DailyForecast.objects.filter(
            created_at__gte=week_ago
        ).aggregate(
            avg_temp=Avg('temperature'),
            avg_high=Avg('high_temperature'),
            avg_low=Avg('low_temperature')
        )

        stats['recent_averages'] = {
            'temperature': round(recent_forecasts['avg_temp'] or 0, 1),
            'high_temperature': round(recent_forecasts['avg_high'] or 0, 1),
            'low_temperature': round(recent_forecasts['avg_low'] or 0, 1),
        }

        return Response(stats)


class ExportAPIView(APIView):
    """API view for exporting forecast data."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """Export forecast data in various formats."""
        export_format = request.data.get('format', 'json')
        location_ids = request.data.get('locations', [])

        if not location_ids:
            return Response({'error': 'No locations specified'}, status=status.HTTP_400_BAD_REQUEST)

        locations = Location.objects.filter(id__in=location_ids)

        if export_format == 'kml':
            return self._export_kml(locations)
        if export_format == 'csv':
            return self._export_csv(locations)
        return self._export_json(locations)

    def _export_json(self, locations):
        """Export as JSON."""
        data = []
        for location in locations:
            location_data = LocationSerializer(location).data
            location_data['forecasts'] = DailyForecastSerializer(
                location.forecasts.all()[:7], many=True
            ).data
            data.append(location_data)

        response = HttpResponse(
            json.dumps(data, indent=2, default=str),
            content_type='application/json'
        )
        response['Content-Disposition'] = 'attachment; filename="weather_export.json"'
        return response

    def _export_csv(self, locations):
        """Export as CSV."""
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Location', 'Date', 'High Temp', 'Low Temp', 'Forecast', 'Wind Speed', 'Wind Direction'
        ])

        for location in locations:
            for forecast in location.forecasts.all()[:7]:
                # Handle both DailyForecast (has high/low) and base ForecastPeriod
                high_temp = getattr(forecast, 'high_temperature', None) or forecast.temperature
                low_temp = getattr(forecast, 'low_temperature', None) or forecast.temperature
                writer.writerow([
                    location.name,
                    forecast.forecast_date,
                    high_temp,
                    low_temp,
                    forecast.short_forecast,
                    forecast.wind_speed,
                    forecast.wind_direction
                ])

        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="weather_export.csv"'
        return response

    def _export_kml(self, locations):
        """Export as KML using existing export utilities."""
        try:
            # This would use your existing export_utils.py
            kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
    <name>Weather Forecast Locations</name>
    {"".join([self._location_to_kml(location) for location in locations])}
</Document>
</kml>"""

            response = HttpResponse(kml_content, content_type='application/vnd.google-earth.kml+xml')
            response['Content-Disposition'] = 'attachment; filename="weather_locations.kml"'
            return response

        except Exception as e:
            return Response({
                'error': 'KML export failed',
                'details': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _location_to_kml(self, location):
        """Convert location to KML placemark."""
        if not location.latitude or not location.longitude:
            return ""

        return f"""
    <Placemark>
        <name>{location.name}</name>
        <description>
            Last updated: {location.last_forecast_update or 'Never'}
            ZIP: {location.zip_code or 'N/A'}
        </description>
        <Point>
            <coordinates>{location.longitude},{location.latitude},0</coordinates>
        </Point>
    </Placemark>"""

# Web view: Alerts list with precomputed counts
class AlertListView(ListView):
    """List active weather alerts for session locations."""
    model = WeatherAlert
    template_name = 'weather/alert_list.html'
    context_object_name = 'alerts'
    paginate_by = 20

    def get_queryset(self):
        qs = WeatherAlert.objects.filter(
            is_active=True,
            expires__gt=timezone.now()
        ).select_related('location').order_by('-severity', '-onset')
        location_ids = self.request.session.get('location_ids')
        if location_ids:
            qs = qs.filter(location_id__in=location_ids)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        alerts = ctx.get('alerts') or []
        severe_extreme = sum(1 for a in alerts if a.severity in ('severe', 'extreme'))
        moderate = sum(1 for a in alerts if a.severity == 'moderate')
        ctx.update({
            'severe_extreme_count': severe_extreme,
            'moderate_count': moderate,
        })
        return ctx


# =============================================================================
# Django Web Interface Views
# =============================================================================


class DashboardView(TemplateView):
    """Main dashboard view with weather overview."""
    template_name = 'weather/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get recent locations (ordered same as location list page)
        # Order: current-location flag first (for saved entries), then by location_type priority, then display_order/name
        type_priority = Case(
            When(location_type='home', then=1),
            When(location_type='work', then=2),
            When(location_type='school', then=3),
            default=4,
            output_field=IntegerField(),
        )

        # Filter locations by session
        location_filter = Q(is_active=True, is_enabled=True)
        location_ids = self.request.session.get('location_ids', [])
        location_filter &= Q(id__in=location_ids)

        locations = (
            Location.objects.filter(location_filter)
            .annotate(type_priority=type_priority)
            .order_by('-is_current_location', 'type_priority', 'display_order', 'name')[:8]
        )

        # Get locations with current conditions
        locations_with_current = (
            Location.objects.filter(location_filter)
            .exclude(current_temp__isnull=True)
            .annotate(type_priority=type_priority)
            .order_by('-is_current_location', 'type_priority', 'display_order', 'name')
        )

        # Select primary location as first in ordered list
        favorite_location = locations[0] if locations else None

        # Get 3-day forecast grouped by date
        daily_forecasts = []
        if favorite_location:
            from collections import defaultdict
            forecasts = (
                DailyForecast.objects.filter(
                    location=favorite_location,
                    forecast_date__gte=timezone.now().date(),
                )
                .order_by('forecast_date', '-is_daytime')[:6]
            )  # Get up to 6 periods (3 days x 2 periods)
            grouped = defaultdict(lambda: {'date': None, 'day': None, 'night': None})
            for forecast in forecasts:
                date = forecast.forecast_date
                grouped[date]['date'] = date
                if forecast.is_daytime:
                    grouped[date]['day'] = forecast
                else:
                    grouped[date]['night'] = forecast
            daily_forecasts = [grouped[date] for date in sorted(grouped.keys())[:3]]

        # Get active alerts ordered by location order
        active_alerts = WeatherAlert.objects.filter(
            is_active=True,
            expires__gt=timezone.now()
        ).select_related('location').annotate(
            type_priority=Case(
                When(location__location_type='home', then=1),
                When(location__location_type='work', then=2),
                When(location__location_type='school', then=3),
                default=4,
                output_field=IntegerField(),
            )
        ).order_by('-location__is_current_location', 'type_priority', 'location__display_order', 'location__name', '-severity', '-onset')[:10]

        # Dashboard statistics
        context.update(
            {
                'locations': locations,
                'locations_with_current': locations_with_current,
                'favorite_location': favorite_location,
                'daily_forecasts': daily_forecasts,
                'active_alerts': active_alerts,
                'total_locations': Location.objects.filter(location_filter).count(),
                'total_forecasts': DailyForecast.objects.count(),
                'recent_alerts': active_alerts,
                'page_title': 'Weather Dashboard',
            }
        )
        return context


class LocationListView(ListView):
    """List view for weather locations."""
    model = Location
    template_name = 'weather/location_list.html'
    context_object_name = 'locations'
    paginate_by = 12

    def get_queryset(self):
        """Get active locations with forecast counts, favorite first."""
        # Filter by session - show all locations including disabled ones on location list page
        location_ids = self.request.session.get('location_ids', [])
        queryset = Location.objects.filter(is_active=True, id__in=location_ids)

        # Search functionality
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(zip_code__icontains=search)
            )

        type_priority = Case(
            When(location_type='home', then=1),
            When(location_type='work', then=2),
            When(location_type='school', then=3),
            default=4,
            output_field=IntegerField(),
        )
        return queryset.annotate(
            forecast_count=Count('forecasts'),
            type_priority=type_priority,
        ).order_by('-is_current_location', 'type_priority', 'display_order', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Weather Locations'
        context['search_query'] = self.request.GET.get('search', '')

        # Fetch current conditions for all locations on page load
        from datetime import date, timedelta
        today = date.today()

        locations_data = []
        for location in context['locations']:
            # Check if current conditions need updating (older than 30 minutes or don't exist)
            needs_update = (
                not location.last_observation_time or
                timezone.now() - location.last_observation_time > timedelta(minutes=30)
            )

            if needs_update:
                fetch_current_conditions(location)

            # Get today's daytime forecast
            today_forecast = DailyForecast.objects.filter(
                location=location,
                forecast_date=today,
                is_daytime=True
            ).first()

            # Get active alerts
            active_alerts = location.alerts.filter(is_active=True)

            locations_data.append({
                'location': location,
                'today_forecast': today_forecast,
                'active_alerts': active_alerts,
                'alert_count': active_alerts.count()
            })

        context['locations_data'] = locations_data

        return context


class LocationDetailView(DetailView):
    """Detail view for individual weather locations."""
    model = Location
    template_name = 'weather/location_detail.html'
    context_object_name = 'location'

    def get_queryset(self):
        return Location.objects.filter(is_active=True).prefetch_related('alerts')

    def get(self, request, *args, **kwargs):
        """Override get to trigger forecast update on page load."""
        self.object = self.get_object()

        # Check if forecast needs updating (older than 1 hour or doesn't exist)
        from datetime import timedelta
        needs_update = (
            not self.object.last_forecast_update or
            timezone.now() - self.object.last_forecast_update > timedelta(hours=1)
        )

        if needs_update and self.object.latitude and self.object.longitude:
            # Fetch current conditions first
            fetch_current_conditions(self.object)

            # Update forecast data
            try:
                from datetime import datetime

                import requests

                headers = {'User-Agent': '(Weather App, contact@example.com)'}

                # Get grid point data
                grid_url = f'https://api.weather.gov/points/{self.object.latitude},{self.object.longitude}'
                grid_response = requests.get(grid_url, headers=headers, timeout=10)
                grid_response.raise_for_status()
                grid_data = grid_response.json()

                # Update NWS grid info
                properties = grid_data.get('properties', {})
                self.object.nws_office = properties.get('gridId', '')
                self.object.grid_x = properties.get('gridX')
                self.object.grid_y = properties.get('gridY')

                # Get forecast URL
                forecast_url = properties.get('forecast')
                if forecast_url:
                    # Fetch forecast data
                    forecast_response = requests.get(forecast_url, headers=headers, timeout=10)
                    forecast_response.raise_for_status()
                    forecast_data = forecast_response.json()

                    # Parse and save forecast periods
                    periods = forecast_data.get('properties', {}).get('periods', [])

                    # Clear old forecasts
                    DailyForecast.objects.filter(location=self.object).delete()

                    # Helper function to parse wind speed
                    def parse_wind_speed(wind_speed_str):
                        if not wind_speed_str:
                            return 0
                        import re
                        numbers = re.findall(r'\d+', str(wind_speed_str))
                        if numbers:
                            if len(numbers) > 1:
                                return int((int(numbers[0]) + int(numbers[1])) / 2)
                            return int(numbers[0])
                        return 0

                    # Create new forecasts
                    for period in periods[:14]:
                        DailyForecast.objects.create(
                            location=self.object,
                            forecast_date=datetime.fromisoformat(period['startTime'].replace('Z', '+00:00')).date(),
                            period_start=datetime.fromisoformat(period['startTime'].replace('Z', '+00:00')),
                            period_end=datetime.fromisoformat(period['endTime'].replace('Z', '+00:00')),
                            is_daytime=period.get('isDaytime', True),
                            temperature=period.get('temperature'),
                            temperature_unit=period.get('temperatureUnit', 'F'),
                            wind_speed=parse_wind_speed(period.get('windSpeed', '')),
                            wind_direction=period.get('windDirection', ''),
                            short_forecast=period.get('shortForecast', ''),
                            detailed_forecast=period.get('detailedForecast', ''),
                            precipitation_probability=period.get('probabilityOfPrecipitation', {}).get('value'),
                        )

                    # Fetch weather alerts
                    try:
                        from weather.models import WeatherAlert
                        alerts_url = f'https://api.weather.gov/alerts/active?point={self.object.latitude},{self.object.longitude}'
                        alerts_response = requests.get(alerts_url, headers=headers, timeout=10)
                        alerts_response.raise_for_status()
                        alerts_data = alerts_response.json()

                        # Deactivate old alerts
                        WeatherAlert.objects.filter(location=self.object).update(is_active=False)

                        # Process each alert
                        features = alerts_data.get('features', [])
                        for feature in features:
                            props = feature.get('properties', {})
                            nws_id = props.get('id')

                            if not nws_id:
                                continue

                            # Parse dates
                            onset = props.get('onset')
                            expires = props.get('expires')

                            if onset:
                                onset = datetime.fromisoformat(onset.replace('Z', '+00:00'))
                            if expires:
                                expires = datetime.fromisoformat(expires.replace('Z', '+00:00'))

                            # Create or update alert
                            WeatherAlert.objects.update_or_create(
                                nws_alert_id=nws_id,
                                defaults={
                                    'location': self.object,
                                    'event': props.get('event', 'Unknown'),
                                    'headline': props.get('headline', ''),
                                    'description': props.get('description', ''),
                                    'severity': props.get('severity', 'unknown').lower(),
                                    'urgency': props.get('urgency', 'unknown').lower(),
                                    'onset': onset,
                                    'expires': expires,
                                    'is_active': True,
                                    'raw_data': props,
                                }
                            )
                    except Exception as e:
                        print(f"Warning: Failed to fetch alerts: {str(e)}")

                    # Update location
                    self.object.last_forecast_update = timezone.now()
                    self.object.save()

            except Exception as e:
                print(f"Warning: Failed to update forecast: {str(e)}")

        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        location = self.object

        # Get all daily forecasts (includes day and night periods)
        all_forecasts = DailyForecast.objects.filter(
            location=location
        ).order_by('period_start')

        # Group forecasts by date (day and night together)
        from itertools import groupby
        grouped_forecasts = []
        for date, periods in groupby(all_forecasts, key=lambda f: f.forecast_date):
            periods_list = list(periods)
            day_forecast = next((p for p in periods_list if p.is_daytime), None)
            night_forecast = next((p for p in periods_list if not p.is_daytime), None)
            grouped_forecasts.append({
                'date': date,
                'day': day_forecast,
                'night': night_forecast
            })

        # Get hourly forecasts
        hourly_forecasts = HourlyForecast.objects.filter(
            location=location,
            period_start__gte=timezone.now()
        ).order_by('period_start')[:24]

        context.update({
            'page_title': f'{location.name} - Weather Details',
            'daily_forecasts': grouped_forecasts,
            'hourly_forecasts': hourly_forecasts,
            'active_alerts': location.alerts.filter(is_active=True),
        })

        return context


def _refresh_forecasts_for_location(location: Location):
    """Fetch and store forecasts for a location using NWS API directly.
    Fallback used by forecast list to guarantee data on first load.
    """
    try:
        import requests
        headers = {'User-Agent': '(Weather App, contact@example.com)'}
        # Get grid point
        grid_url = f'https://api.weather.gov/points/{location.latitude},{location.longitude}'
        grid_response = requests.get(grid_url, headers=headers, timeout=10)
        grid_response.raise_for_status()
        grid_data = grid_response.json()
        props = grid_data.get('properties', {})
        location.nws_office = props.get('gridId', '')
        location.grid_x = props.get('gridX')
        location.grid_y = props.get('gridY')
        # Forecast URL
        fcst_url = props.get('forecast')
        if not fcst_url:
            return False
        r = requests.get(fcst_url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        periods = data.get('properties', {}).get('periods', [])
        # Replace existing
        DailyForecast.objects.filter(location=location).delete()
        from datetime import datetime
        def parse_ws(ws):
            if not ws:
                return 0
            import re
            nums = re.findall(r'\d+', str(ws))
            if not nums:
                return 0
            if len(nums) > 1:
                return int((int(nums[0]) + int(nums[1])) / 2)
            return int(nums[0])
        for p in periods[:14]:
            DailyForecast.objects.create(
                location=location,
                forecast_date=datetime.fromisoformat(p['startTime'].replace('Z', '+00:00')).date(),
                period_start=datetime.fromisoformat(p['startTime'].replace('Z', '+00:00')),
                period_end=datetime.fromisoformat(p['endTime'].replace('Z', '+00:00')),
                is_daytime=p.get('isDaytime', True),
                temperature=p.get('temperature'),
                temperature_unit=p.get('temperatureUnit', 'F'),
                wind_speed=parse_ws(p.get('windSpeed', '')),
                wind_direction=p.get('windDirection', ''),
                short_forecast=p.get('shortForecast', ''),
                detailed_forecast=p.get('detailedForecast', ''),
                precipitation_probability=p.get('probabilityOfPrecipitation', {}).get('value'),
            )
        location.last_forecast_update = timezone.now()
        location.save(update_fields=['nws_office','grid_x','grid_y','last_forecast_update'])
        return True
    except Exception:
        logger.exception('Forecast refresh failed for %s', location.name)
        return False


class ForecastListView(ListView):
    """List view for weather forecasts."""
    model = DailyForecast
    template_name = 'weather/forecast_list.html'
    context_object_name = 'forecasts'
    paginate_by = None  # Show all forecasts

    def get_queryset(self):
        """Get forecasts for active locations."""
        # Ensure forecasts are available/up-to-date on page load
        threshold = timezone.now() - timedelta(minutes=30)

        # Filter locations by session - only show enabled locations
        location_ids = self.request.session.get('location_ids', [])
        active_locations = Location.objects.filter(is_active=True, is_enabled=True, id__in=location_ids)
        for loc in active_locations:
            has_upcoming = DailyForecast.objects.filter(
                location=loc,
                forecast_date__gte=timezone.now().date()
            ).exists()
            if not has_upcoming or not loc.last_forecast_update or loc.last_forecast_update < threshold:
                # Try backend service first
                try:
                    from .services import SyncWeatherService
                    SyncWeatherService.update_forecasts_for_location(loc)
                except Exception:
                    # Service failed, fallback to direct NWS
                    _refresh_forecasts_for_location(loc)
                else:
                    # If service didn't create forecasts, fallback
                    has_after = DailyForecast.objects.filter(
                        location=loc,
                        forecast_date__gte=timezone.now().date()
                    ).exists()
                    if not has_after:
                        _refresh_forecasts_for_location(loc)
        qs = DailyForecast.objects.select_related('location').filter(
            location__is_active=True,
            location__is_enabled=True,
            forecast_date__gte=timezone.now().date()
        )
        type_priority = Case(
            When(location__location_type='home', then=1),
            When(location__location_type='work', then=2),
            When(location__location_type='school', then=3),
            default=4,
            output_field=IntegerField(),
        )
        return qs.annotate(type_priority=type_priority).order_by('-location__is_current_location', 'type_priority', 'location__display_order', 'location__name', 'forecast_date', '-is_daytime')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Weather Forecasts'

        # Add current conditions for each location
        type_priority = Case(
            When(location_type='home', then=1),
            When(location_type='work', then=2),
            When(location_type='school', then=3),
            default=4,
            output_field=IntegerField(),
        )
        # Filter locations by session - only show enabled locations
        location_ids = self.request.session.get('location_ids', [])
        location_filter = Q(is_active=True, is_enabled=True, id__in=location_ids)

        locations = Location.objects.filter(location_filter).exclude(current_temp__isnull=True).annotate(type_priority=type_priority).order_by('-is_current_location', 'type_priority', 'display_order', 'name')
        context['locations_with_current'] = locations

        # Group forecasts by date first, then by location
        from collections import defaultdict
        dates_forecasts = defaultdict(dict)

        for forecast in context['forecasts']:
            date = forecast.forecast_date
            location_id = forecast.location.id
            if location_id not in dates_forecasts[date]:
                dates_forecasts[date][location_id] = {
                    'location': forecast.location,
                    'day': None,
                    'night': None
                }
            if forecast.is_daytime:
                dates_forecasts[date][location_id]['day'] = forecast
            else:
                dates_forecasts[date][location_id]['night'] = forecast

        # Convert to list format grouped by date with sorted locations
        grouped_by_date = []
        for date in sorted(dates_forecasts.keys()):
            # Sort locations by current flag, type priority, display_order, name
            locations_dict = dates_forecasts[date]
            sorted_locations = sorted(
                locations_dict.values(),
                key=lambda x: (
                    0 if x['location'].is_current_location else 1,
                    (1 if x['location'].location_type == 'home' else 2 if x['location'].location_type == 'work' else 3 if x['location'].location_type == 'school' else 4),
                    x['location'].display_order,
                    x['location'].name
                )
            )

            grouped_by_date.append({
                'date': date,
                'locations': sorted_locations
            })

        context['grouped_by_date'] = grouped_by_date

        return context


# Duplicate AlertListView removed to avoid F811 redefinition; earlier definition retained.
