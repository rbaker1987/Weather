from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import Location, HourlyForecast
from ..serializers import HourlyForecastSerializer
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.db.models import Q
import requests
from datetime import datetime, timedelta
import logging

logger = logging.getLogger('weather')

class HourlyForecastForLocationAPIView(APIView):
    """
    Returns hourly forecast for a location and date, or next N hours for lat/lon.
    GET params:
      - lat, lon: coordinates (required for next N hours)
      - date: YYYY-MM-DD (optional, for daily modal)
      - hours: int (optional, default 6)
    """
    def get(self, request):
        lat = request.GET.get('lat')
        lon = request.GET.get('lon')
        date_str = request.GET.get('date')
        hours_count = int(request.GET.get('hours', 6))
        
        if not lat or not lon:
            return Response({'error': 'lat and lon are required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Fetch hourly forecast from NWS API
            headers = {'User-Agent': '(Weather App, contact@example.com)'}
            
            # Get grid point
            grid_url = f'https://api.weather.gov/points/{float(lat):.4f},{float(lon):.4f}'
            grid_response = requests.get(grid_url, headers=headers, timeout=10)
            grid_response.raise_for_status()
            grid_data = grid_response.json()
            
            # Get hourly forecast URL
            hourly_forecast_url = grid_data.get('properties', {}).get('forecastHourly')
            if not hourly_forecast_url:
                return Response({'error': 'Hourly forecast not available'}, status=status.HTTP_404_NOT_FOUND)
            
            # Fetch hourly forecast
            hourly_response = requests.get(hourly_forecast_url, headers=headers, timeout=10)
            hourly_response.raise_for_status()
            hourly_data = hourly_response.json()
            
            periods = hourly_data.get('properties', {}).get('periods', [])
            
            # Filter by date if provided
            if date_str:
                target_date = parse_date(date_str)
                if target_date:
                    filtered_periods = [
                        p for p in periods 
                        if datetime.fromisoformat(p['startTime'].replace('Z', '+00:00')).date() == target_date
                    ]
                    periods = filtered_periods
            
            # Limit to requested number of hours
            periods = periods[:hours_count]
            
            # Format for JS
            hours_data = []
            for period in periods:
                start_time = datetime.fromisoformat(period['startTime'].replace('Z', '+00:00'))
                hours_data.append({
                    'time': start_time.strftime('%I %p').lstrip('0'),
                    'temp': period.get('temperature', 'N/A'),
                    'condition': period.get('shortForecast', 'N/A'),
                    'icon': self._get_weather_icon(period.get('shortForecast', '')),
                    'wind': period.get('windSpeed', ''),
                    'windDir': period.get('windDirection', ''),
                })
            
            return Response({'hours': hours_data}, status=status.HTTP_200_OK)
            
        except requests.RequestException as e:
            logger.error(f"NWS API error: {e}")
            return Response({'error': 'Failed to fetch forecast data'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            logger.error(f"Error processing hourly forecast: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_weather_icon(self, conditions):
        """Return Font Awesome icon name for weather condition."""
        c = conditions.lower()
        if 'storm' in c or 'thunder' in c or 't-storm' in c:
            return 'bolt'
        if 'ice' in c or 'icy' in c or 'freezing' in c or 'sleet' in c:
            return 'icicles'
        if 'snow' in c or 'flurries' in c or 'blizzard' in c:
            return 'snowflake'
        if 'fog' in c or 'mist' in c or 'haze' in c:
            return 'smog'
        if 'rain' in c or 'shower' in c or 'drizzle' in c:
            return 'cloud-rain'
        if 'wind' in c and not 'cloudy' in c:
            return 'wind'
        if 'partly' in c:
            return 'cloud-sun'
        if 'sunny' in c or 'clear' in c or 'fair' in c:
            return 'sun'
        if 'cloud' in c or 'overcast' in c:
            return 'cloud'
        return 'cloud-sun'
