"""Django REST Framework views for weather API."""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from django.db.models import Q, Count, Avg
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.core.cache import cache
from datetime import datetime, timedelta
import asyncio
import json
import tempfile
import logging

from .models import Location, HourlyForecast, DailyForecast, WeatherAlert, ForecastRequest
from .serializers import (
    LocationSerializer, LocationCreateSerializer, HourlyForecastSerializer,
    DailyForecastSerializer, WeatherAlertSerializer, ForecastRequestSerializer,
    BulkForecastRequestSerializer
)

logger = logging.getLogger('weather')


class LocationViewSet(viewsets.ModelViewSet):
    """API ViewSet for managing locations."""
    
    queryset = Location.objects.filter(is_active=True)
    serializer_class = LocationSerializer
    permission_classes = [permissions.AllowAny]
    search_fields = ['name', 'zip_code']
    ordering_fields = ['name', 'created_at', 'last_forecast_update']
    ordering = ['name']

    def get_queryset(self):
        """Filter locations by user if authenticated."""
        queryset = super().get_queryset()
        
        if self.request.user.is_authenticated:
            # Show user's locations first, then public ones
            user_locations = Q(created_by=self.request.user)
            public_locations = Q(created_by__isnull=True)
            queryset = queryset.filter(user_locations | public_locations)
        
        return queryset.annotate(
            forecast_count=Count('forecasts')
        )

    def perform_create(self, serializer):
        """Set created_by to current user and geocode if needed."""
        location = serializer.save(
            created_by=self.request.user if self.request.user.is_authenticated else None
        )
        
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
                print(f"Geocoding error: {str(e)}")

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
                from datetime import datetime, time
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
                    from datetime import timedelta
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
                            if wind_speed_kmh is not None and wind_speed_kmh != 0:
                                try:
                                    # Wind speed from NWS is in km/h, convert to mph
                                    location.current_wind_speed = int(wind_speed_kmh * 0.621371)
                                except (ValueError, TypeError):
                                    location.current_wind_speed = None
                            else:
                                location.current_wind_speed = None
                            
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
                            
                            timestamp = obs_props.get('timestamp')
                            if timestamp:
                                location.last_observation_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
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
            user=request.user if request.user.is_authenticated else None,
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
            return Response({
                'error': 'No locations specified'
            }, status=status.HTTP_400_BAD_REQUEST)

        locations = Location.objects.filter(id__in=location_ids)
        
        if export_format == 'kml':
            return self._export_kml(locations)
        elif export_format == 'csv':
            return self._export_csv(locations)
        else:
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
                writer.writerow([
                    location.name,
                    forecast.forecast_date,
                    forecast.high_temperature or forecast.temperature,
                    forecast.low_temperature or forecast.temperature,
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


# =============================================================================
# Django Web Interface Views
# =============================================================================

from django.views.generic import TemplateView, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch


class DashboardView(TemplateView):
    """Main dashboard view with weather overview."""
    template_name = 'weather/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get recent locations and forecasts for dashboard
        recent_locations = Location.objects.filter(is_active=True)[:5]
        
        # Dashboard statistics
        context.update({
            'recent_locations': recent_locations,
            'total_locations': Location.objects.filter(is_active=True).count(),
            'total_forecasts': DailyForecast.objects.count(),
            'recent_alerts': WeatherAlert.objects.filter(
                is_active=True
            ).order_by('-onset')[:5],
            'page_title': 'Weather Dashboard',
        })
        
        return context


class LocationListView(ListView):
    """List view for weather locations."""
    model = Location
    template_name = 'weather/location_list.html'
    context_object_name = 'locations'
    paginate_by = 12
    
    def get_queryset(self):
        """Get active locations with forecast counts."""
        queryset = Location.objects.filter(is_active=True)
        
        # Search functionality
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(zip_code__icontains=search)
            )
        
        return queryset.annotate(
            forecast_count=Count('forecasts')
        ).order_by('name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Weather Locations'
        context['search_query'] = self.request.GET.get('search', '')
        
        # Add today's forecast and alerts for each location
        from datetime import date
        today = date.today()
        
        locations_data = []
        for location in context['locations']:
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
            # Trigger forecast update in background
            try:
                import requests
                from datetime import datetime
                
                # Get grid point data
                grid_url = f'https://api.weather.gov/points/{self.object.latitude},{self.object.longitude}'
                headers = {'User-Agent': '(Weather App, contact@example.com)'}
                
                grid_response = requests.get(grid_url, headers=headers, timeout=10)
                grid_response.raise_for_status()
                grid_data = grid_response.json()
                
                # Update NWS grid info
                properties = grid_data.get('properties', {})
                self.object.nws_office = properties.get('gridId', '')
                self.object.grid_x = properties.get('gridX')
                self.object.grid_y = properties.get('gridY')
                
                # Fetch current conditions
                try:
                    observation_stations_url = properties.get('observationStations')
                    if observation_stations_url:
                        stations_response = requests.get(observation_stations_url, headers=headers, timeout=10)
                        stations_response.raise_for_status()
                        stations_data = stations_response.json()
                        
                        stations = stations_data.get('features', [])
                        if stations:
                            station_id = stations[0].get('properties', {}).get('stationIdentifier')
                            if station_id:
                                obs_url = f'https://api.weather.gov/stations/{station_id}/observations/latest'
                                obs_response = requests.get(obs_url, headers=headers, timeout=10)
                                obs_response.raise_for_status()
                                obs_data = obs_response.json()
                                
                                obs_props = obs_data.get('properties', {})
                                
                                temp_c = obs_props.get('temperature', {}).get('value')
                                if temp_c:
                                    self.object.current_temp = int(temp_c * 9/5 + 32)
                                
                                self.object.current_conditions = obs_props.get('textDescription', '')
                                
                                humidity = obs_props.get('relativeHumidity', {}).get('value')
                                if humidity:
                                    self.object.current_humidity = int(humidity)
                                
                                wind_speed_kmh = obs_props.get('windSpeed', {}).get('value')
                                if wind_speed_kmh is not None and wind_speed_kmh != 0:
                                    try:
                                        # Wind speed from NWS is in km/h, convert to mph
                                        self.object.current_wind_speed = int(wind_speed_kmh * 0.621371)
                                    except (ValueError, TypeError):
                                        self.object.current_wind_speed = None
                                else:
                                    self.object.current_wind_speed = None
                                
                                wind_dir_deg = obs_props.get('windDirection', {}).get('value')
                                if wind_dir_deg is not None:
                                    try:
                                        deg = float(wind_dir_deg)
                                        directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
                                        self.object.current_wind_direction = directions[int((deg + 22.5) / 45) % 8]
                                    except (ValueError, TypeError):
                                        self.object.current_wind_direction = ''
                                else:
                                    self.object.current_wind_direction = ''
                                
                                timestamp = obs_props.get('timestamp')
                                if timestamp:
                                    self.object.last_observation_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except Exception as e:
                    print(f"Warning: Could not fetch current conditions: {str(e)}")
                
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


class ForecastListView(ListView):
    """List view for weather forecasts."""
    model = DailyForecast
    template_name = 'weather/forecast_list.html'
    context_object_name = 'forecasts'
    paginate_by = 20
    
    def get_queryset(self):
        """Get forecasts for active locations."""
        return DailyForecast.objects.select_related('location').filter(
            location__is_active=True,
            forecast_date__gte=timezone.now().date()
        ).order_by('forecast_date', 'location__name')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Weather Forecasts'
        
        # Add current conditions for each location
        locations = Location.objects.filter(is_active=True).exclude(current_temp__isnull=True)
        context['locations_with_current'] = locations
        
        return context


class AlertListView(ListView):
    """List view for weather alerts."""
    model = WeatherAlert
    template_name = 'weather/alert_list.html'
    context_object_name = 'alerts'
    paginate_by = 20
    
    def get_queryset(self):
        """Get active alerts for active locations."""
        return WeatherAlert.objects.select_related('location').filter(
            location__is_active=True,
            is_active=True
        ).order_by('-onset')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Weather Alerts'
        return context