"""Django service integration with weather backend components.

This module provides Django-specific services that integrate with
the weather application components now contained within the Django app.
"""

import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import logging

from django.conf import settings
from django.utils import timezone
from django.db import transaction
from asgiref.sync import sync_to_async, async_to_sync

try:
    from .api.nws_client import WeatherService
    from .utils.geocoding import create_location_from_string, bulk_geocode_locations
    from .core.models import Location as PydanticLocation, HourlyForecast as PydanticHourly, DailyForecast as PydanticDaily
    from .utils.datetime_utils import parse_nws_datetime
    WEATHER_BACKEND_AVAILABLE = True
except ImportError as e:
    WEATHER_BACKEND_AVAILABLE = False
    import warnings
    warnings.warn(f"Weather backend components not available: {e}")

from .models import Location, HourlyForecast, DailyForecast, WeatherAlert, ForecastRequest

logger = logging.getLogger('weather')


class WeatherIntegrationService:
    """Service for integrating Django models with existing weather_app logic."""
    
    def __init__(self):
        self.weather_service = None
        if WEATHER_BACKEND_AVAILABLE:
            self.weather_service = WeatherService()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.weather_service:
            await self.weather_service.close()

    @sync_to_async
    def get_location_by_id(self, location_id: str) -> Optional[Location]:
        """Get Django location by ID."""
        try:
            return Location.objects.get(id=location_id, is_active=True)
        except Location.DoesNotExist:
            return None

    @sync_to_async
    def get_all_active_locations(self) -> List[Location]:
        """Get all active Django locations."""
        return list(Location.objects.filter(is_active=True))

    async def create_location_from_input(self, location_input: str) -> Optional[Location]:
        """Create a Django location from string input using existing geocoding logic.\"\"\""
        if not WEATHER_BACKEND_AVAILABLE:
            logger.error("Weather backend components not available")
            return None

        try:
            # Use existing geocoding service
            pydantic_location = await create_location_from_string(location_input)
            if not pydantic_location:
                logger.warning(f"Could not geocode location: {location_input}")
                return None

            # Create Django location from Pydantic model
            django_location = await self.pydantic_to_django_location(pydantic_location)
            return django_location

        except Exception as e:
            logger.error(f"Error creating location from input '{location_input}': {e}")
            return None

    @sync_to_async
    def pydantic_to_django_location(self, pydantic_location: PydanticLocation) -> Location:
        """Convert Pydantic location to Django model."""
        
        # Check if location already exists
        existing = Location.objects.filter(
            name=pydantic_location.name,
            is_active=True
        ).first()
        
        if existing:
            return existing

        # Create new location
        django_location = Location.objects.create(
            name=pydantic_location.name,
            zip_code=pydantic_location.zip_code or '',
            is_active=True
        )
        
        # Set coordinates if available
        if pydantic_location.latitude and pydantic_location.longitude:
            django_location.latitude = pydantic_location.latitude
            django_location.longitude = pydantic_location.longitude
            django_location.save()
        
        logger.info(f"Created new Django location: {django_location.name}")
        return django_location

    async def update_forecasts_for_location(self, location: Location) -> Dict[str, Any]:
        """Update forecasts for a specific location using existing weather service."""
        if not WEATHER_BACKEND_AVAILABLE or not self.weather_service:
            return {'error': 'Weather service not available'}

        try:
            # Convert Django location to Pydantic
            pydantic_location = PydanticLocation(
                name=location.name,
                latitude=location.latitude,
                longitude=location.longitude,
                zip_code=location.zip_code or None
            )

            # Get forecasts using existing service
            forecasts = await self.weather_service.get_forecasts_for_locations([pydantic_location])
            
            if not forecasts:
                return {'error': 'No forecast data received'}

            location_forecasts = forecasts.get(location.name, {})
            
            # Save forecasts to Django models
            daily_count = await self.save_daily_forecasts(location, location_forecasts.get('daily', []))
            hourly_count = await self.save_hourly_forecasts(location, location_forecasts.get('hourly', []))
            
            # Update location timestamp
            await sync_to_async(self._update_location_timestamp)(location)
            
            return {
                'success': True,
                'daily_forecasts': daily_count,
                'hourly_forecasts': hourly_count,
                'updated_at': timezone.now()
            }

        except Exception as e:
            logger.error(f"Error updating forecasts for {location.name}: {e}")
            return {'error': str(e)}

    def _update_location_timestamp(self, location: Location):
        """Update the last forecast update timestamp."""
        location.last_forecast_update = timezone.now()
        location.save(update_fields=['last_forecast_update'])

    @sync_to_async
    def save_daily_forecasts(self, location: Location, pydantic_forecasts: List[PydanticDaily]) -> int:
        """Save daily forecasts to Django models."""
        count = 0
        with transaction.atomic():
            for forecast in pydantic_forecasts:
                django_forecast, created = DailyForecast.objects.update_or_create(
                    location=location,
                    forecast_date=forecast.date,
                    period_start=forecast.period_start,
                    period_end=forecast.period_end,
                    defaults={
                        'is_daytime': getattr(forecast, 'is_daytime', True),
                        'temperature': forecast.temperature.value,
                        'temperature_unit': forecast.temperature.unit.value,
                        'high_temperature': forecast.high_temperature.value if forecast.high_temperature else None,
                        'low_temperature': forecast.low_temperature.value if forecast.low_temperature else None,
                        'short_forecast': forecast.short_forecast or '',
                        'detailed_forecast': forecast.detailed_forecast or '',
                        'wind_speed': forecast.wind_condition.speed if forecast.wind_condition else 0,
                        'wind_direction': forecast.wind_condition.direction if forecast.wind_condition else '',
                        'wind_gust': forecast.wind_condition.gust if forecast.wind_condition else None,
                        'precipitation_probability': getattr(forecast, 'precipitation_probability', None),
                    }
                )
                if created:
                    count += 1
                    
        logger.info(f"Saved {count} daily forecasts for {location.name}")
        return count

    @sync_to_async  
    def save_hourly_forecasts(self, location: Location, pydantic_forecasts: List[PydanticHourly]) -> int:
        """Save hourly forecasts to Django models."""
        count = 0
        with transaction.atomic():
            for forecast in pydantic_forecasts:
                django_forecast, created = HourlyForecast.objects.update_or_create(
                    location=location,
                    period_start=forecast.period_start,
                    period_end=forecast.period_end,
                    defaults={
                        'forecast_date': forecast.date,
                        'temperature': forecast.temperature.value,
                        'temperature_unit': forecast.temperature.unit.value,
                        'short_forecast': forecast.short_forecast or '',
                        'detailed_forecast': forecast.detailed_forecast or '',
                        'wind_speed': forecast.wind_condition.speed if forecast.wind_condition else 0,
                        'wind_direction': forecast.wind_condition.direction if forecast.wind_condition else '',
                        'wind_gust': forecast.wind_condition.gust if forecast.wind_condition else None,
                        'precipitation_probability': getattr(forecast, 'precipitation_probability', None),
                        'humidity': getattr(forecast, 'humidity', None),
                        'dew_point': getattr(forecast, 'dew_point', None),
                    }
                )
                if created:
                    count += 1
                    
        logger.info(f"Saved {count} hourly forecasts for {location.name}")
        return count

    async def bulk_update_forecasts(self, location_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Update forecasts for multiple locations."""
        if location_ids:
            locations = []
            for location_id in location_ids:
                location = await self.get_location_by_id(location_id)
                if location:
                    locations.append(location)
        else:
            locations = await self.get_all_active_locations()

        results = []
        for location in locations:
            result = await self.update_forecasts_for_location(location)
            results.append({
                'location': location.name,
                'location_id': str(location.id),
                'result': result
            })

        return {
            'success': True,
            'total_locations': len(locations),
            'results': results,
            'updated_at': timezone.now()
        }

    async def cleanup_old_forecasts(self, days_to_keep: int = 30) -> Dict[str, int]:
        """Clean up old forecast data."""
        cutoff_date = timezone.now() - timedelta(days=days_to_keep)
        
        daily_deleted = await sync_to_async(
            lambda: DailyForecast.objects.filter(created_at__lt=cutoff_date).delete()[0]
        )()
        
        hourly_deleted = await sync_to_async(
            lambda: HourlyForecast.objects.filter(created_at__lt=cutoff_date).delete()[0]
        )()
        
        logger.info(f"Cleaned up {daily_deleted} daily and {hourly_deleted} hourly forecasts")
        
        return {
            'daily_deleted': daily_deleted,
            'hourly_deleted': hourly_deleted,
            'cutoff_date': cutoff_date
        }


# Sync wrapper functions for use in Django views
class SyncWeatherService:
    """Synchronous wrapper for async weather service."""
    
    @staticmethod
    def create_location_from_input(location_input: str, user=None) -> Optional[Location]:
        """Sync version of create_location_from_input."""
        async def _async_create():
            async with WeatherIntegrationService() as service:
                return await service.create_location_from_input(location_input, user)
        
        return async_to_sync(_async_create)()
    
    @staticmethod
    def update_forecasts_for_location(location: Location) -> Dict[str, Any]:
        """Sync version of update_forecasts_for_location."""
        async def _async_update():
            async with WeatherIntegrationService() as service:
                return await service.update_forecasts_for_location(location)
        
        return async_to_sync(_async_update)()
    
    @staticmethod
    def bulk_update_forecasts(location_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Sync version of bulk_update_forecasts."""
        async def _async_bulk_update():
            async with WeatherIntegrationService() as service:
                return await service.bulk_update_forecasts(location_ids)
        
        return async_to_sync(_async_bulk_update)()


# Export utilities for use in other Django modules
def get_weather_service():
    """Get a weather integration service instance."""
    return WeatherIntegrationService()

def is_weather_backend_available():
    """Check if weather backend components are available."""
    return WEATHER_BACKEND_AVAILABLE