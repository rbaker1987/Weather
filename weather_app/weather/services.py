"""Django service integration with weather backend components.

This module provides Django-specific services that integrate with
the weather application components now contained within the Django app.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from asgiref.sync import async_to_sync, sync_to_async
from django.db import transaction
from django.utils import timezone

try:
    from .api.nws_client import WeatherService
    from .core.models import DailyForecast as PydanticDaily
    from .core.models import HourlyForecast as PydanticHourly
    from .core.models import Location as PydanticLocation
    from .utils.geocoding import create_location_from_string

    WEATHER_BACKEND_AVAILABLE = True
except ImportError as e:
    WEATHER_BACKEND_AVAILABLE = False
    import warnings

    warnings.warn(f"Weather backend components not available: {e}", stacklevel=2)

from .models import DailyForecast, HourlyForecast, Location

logger = logging.getLogger("weather")


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
    def get_location_by_id(self, location_id: str) -> Location | None:
        """Get Django location by ID."""
        try:
            return Location.objects.get(id=location_id, is_active=True)
        except Location.DoesNotExist:
            return None

    @sync_to_async
    def get_all_active_locations(self) -> list[Location]:
        """Get all active Django locations."""
        return list(Location.objects.filter(is_active=True))

    async def create_location_from_input(self, location_input: str) -> Location | None:
        """Create a Django location from string input using existing geocoding logic."""
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
            return await self.pydantic_to_django_location(pydantic_location)

        except Exception as e:
            logger.error(f"Error creating location from input '{location_input}': {e}")
            return None

    @sync_to_async
    def pydantic_to_django_location(
        self, pydantic_location: PydanticLocation
    ) -> Location:
        """Convert Pydantic location to Django model."""

        # Check if location already exists
        existing = Location.objects.filter(
            name=pydantic_location.name, is_active=True
        ).first()

        if existing:
            return existing

        # Create new location
        django_location = Location.objects.create(
            name=pydantic_location.name,
            zip_code=pydantic_location.zip_code or "",
            is_active=True,
        )

        # Set coordinates if available
        if pydantic_location.latitude and pydantic_location.longitude:
            django_location.latitude = pydantic_location.latitude
            django_location.longitude = pydantic_location.longitude
            django_location.save()

        logger.info(f"Created new Django location: {django_location.name}")
        return django_location

    async def update_forecasts_for_location(self, location: Location) -> dict[str, Any]:
        """Update forecasts for a specific location using existing weather service."""
        if not WEATHER_BACKEND_AVAILABLE or not self.weather_service:
            return {"error": "Weather service not available"}

        try:
            # Convert Django location to Pydantic
            pydantic_location = PydanticLocation(
                name=location.name,
                latitude=location.latitude,
                longitude=location.longitude,
                zip_code=location.zip_code or None,
            )

            # Get forecasts using existing service
            forecasts = await self.weather_service.get_forecasts_for_locations(
                [pydantic_location]
            )

            if not forecasts:
                return {"error": "No forecast data received"}

            location_forecasts = forecasts.get(location.name, {})

            # Save forecasts to Django models
            daily_count = await self.save_daily_forecasts(
                location, location_forecasts.get("daily", [])
            )
            hourly_count = await self.save_hourly_forecasts(
                location, location_forecasts.get("hourly", [])
            )

            # Update location timestamp
            await sync_to_async(self._update_location_timestamp)(location)

            return {
                "success": True,
                "daily_forecasts": daily_count,
                "hourly_forecasts": hourly_count,
                "updated_at": timezone.now(),
            }

        except Exception as e:
            logger.error(f"Error updating forecasts for {location.name}: {e}")
            return {"error": str(e)}

    def _update_location_timestamp(self, location: Location):
        """Update the last forecast update timestamp."""
        location.last_forecast_update = timezone.now()
        location.save(update_fields=["last_forecast_update"])

    @sync_to_async
    def save_daily_forecasts(
        self, location: Location, pydantic_forecasts: list[PydanticDaily]
    ) -> int:
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
                        "is_daytime": getattr(forecast, "is_daytime", True),
                        "temperature": forecast.temperature.value,
                        "temperature_unit": forecast.temperature.unit.value,
                        "high_temperature": forecast.high_temperature.value
                        if forecast.high_temperature
                        else None,
                        "low_temperature": forecast.low_temperature.value
                        if forecast.low_temperature
                        else None,
                        "short_forecast": forecast.short_forecast or "",
                        "detailed_forecast": forecast.detailed_forecast or "",
                        "wind_speed": forecast.wind_condition.speed
                        if forecast.wind_condition
                        else 0,
                        "wind_direction": forecast.wind_condition.direction
                        if forecast.wind_condition
                        else "",
                        "wind_gust": forecast.wind_condition.gust
                        if forecast.wind_condition
                        else None,
                        "precipitation_probability": getattr(
                            forecast, "precipitation_probability", None
                        ),
                    },
                )
                if created:
                    count += 1

        logger.info(f"Saved {count} daily forecasts for {location.name}")
        return count

    @sync_to_async
    def save_hourly_forecasts(
        self, location: Location, pydantic_forecasts: list[PydanticHourly]
    ) -> int:
        """Save hourly forecasts to Django models."""
        count = 0
        with transaction.atomic():
            for forecast in pydantic_forecasts:
                django_forecast, created = HourlyForecast.objects.update_or_create(
                    location=location,
                    period_start=forecast.period_start,
                    period_end=forecast.period_end,
                    defaults={
                        "forecast_date": forecast.date,
                        "temperature": forecast.temperature.value,
                        "temperature_unit": forecast.temperature.unit.value,
                        "short_forecast": forecast.short_forecast or "",
                        "detailed_forecast": forecast.detailed_forecast or "",
                        "wind_speed": forecast.wind_condition.speed
                        if forecast.wind_condition
                        else 0,
                        "wind_direction": forecast.wind_condition.direction
                        if forecast.wind_condition
                        else "",
                        "wind_gust": forecast.wind_condition.gust
                        if forecast.wind_condition
                        else None,
                        "precipitation_probability": getattr(
                            forecast, "precipitation_probability", None
                        ),
                        "humidity": getattr(forecast, "humidity", None),
                        "dew_point": getattr(forecast, "dew_point", None),
                    },
                )
                if created:
                    count += 1

        logger.info(f"Saved {count} hourly forecasts for {location.name}")
        return count

    async def bulk_update_forecasts(
        self, location_ids: list[str] | None = None
    ) -> dict[str, Any]:
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
            results.append(
                {
                    "location": location.name,
                    "location_id": str(location.id),
                    "result": result,
                }
            )

        return {
            "success": True,
            "total_locations": len(locations),
            "results": results,
            "updated_at": timezone.now(),
        }

    async def cleanup_old_forecasts(self, days_to_keep: int = 30) -> dict[str, int]:
        """Clean up old forecast data."""
        cutoff_date = timezone.now() - timedelta(days=days_to_keep)

        daily_deleted = await sync_to_async(
            lambda: DailyForecast.objects.filter(created_at__lt=cutoff_date).delete()[0]
        )()

        hourly_deleted = await sync_to_async(
            lambda: HourlyForecast.objects.filter(created_at__lt=cutoff_date).delete()[
                0
            ]
        )()

        logger.info(
            f"Cleaned up {daily_deleted} daily and {hourly_deleted} hourly forecasts"
        )

        return {
            "daily_deleted": daily_deleted,
            "hourly_deleted": hourly_deleted,
            "cutoff_date": cutoff_date,
        }


# Sync wrapper functions for use in Django views
class SyncWeatherService:
    """Synchronous wrapper for async weather service."""

    @staticmethod
    def create_location_from_input(location_input: str, _user=None) -> Location | None:
        """Sync version of create_location_from_input."""

        async def _async_create():
            async with WeatherIntegrationService() as service:
                return await service.create_location_from_input(location_input)

        return async_to_sync(_async_create)()

    @staticmethod
    def update_forecasts_for_location(location: Location) -> dict[str, Any]:
        """Sync version of update_forecasts_for_location."""

        async def _async_update():
            async with WeatherIntegrationService() as service:
                return await service.update_forecasts_for_location(location)

        return async_to_sync(_async_update)()

    @staticmethod
    def bulk_update_forecasts(
        location_ids: list[str] | None = None,
    ) -> dict[str, Any]:
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


# ============================================================================
# Cache-aware data fetching services for CurrentConditions and Forecasts
# ============================================================================


class CurrentConditionsService:
    """Service for fetching current conditions with 15-minute cache validation."""

    @staticmethod
    def get_or_fetch_current_conditions(location: Location, force_refresh: bool = False):
        """
        Get current conditions for a location.

        Strategy:
        1. If force_refresh is True, fetch from API regardless of cache age
        2. If no cached data exists, fetch from API
        3. If cached data is stale (>15 min), fetch from API
        4. Otherwise, return cached data

        Args:
            location: Location instance
            force_refresh: If True, bypass cache and fetch fresh data

        Returns:
            CurrentConditions instance or None if fetch fails
        """
        from .models import CurrentConditions

        try:
            current_conditions = location.current_conditions_cache
        except CurrentConditions.DoesNotExist:
            current_conditions = None

        # Check if we need to fetch fresh data
        should_fetch = force_refresh or current_conditions is None or current_conditions.is_stale

        if should_fetch:
            logger.info(
                f"Fetching fresh current conditions for {location.name} "
                f"(force_refresh={force_refresh}, exists={current_conditions is not None}, "
                f"stale={current_conditions.is_stale if current_conditions else 'N/A'})"
            )
            return CurrentConditionsService.fetch_and_cache_current_conditions(location)
        else:
            age_minutes = int((timezone.now() - current_conditions.updated_at).total_seconds() / 60)
            logger.info(
                f"Returning cached current conditions for {location.name} "
                f"(age={age_minutes} minutes)"
            )
            return current_conditions

    @staticmethod
    def fetch_and_cache_current_conditions(location: Location):
        """
        Fetch current conditions from API and cache in database.

        This integrates with existing fetch_current_conditions logic from views.

        Args:
            location: Location instance

        Returns:
            CurrentConditions instance or None if fetch fails
        """
        from .models import CurrentConditions

        if not location.latitude or not location.longitude:
            logger.warning(f"Location {location.name} has no coordinates, skipping fetch")
            return None

        try:
            import requests

            headers = {"User-Agent": "(Weather App, contact@example.com)"}

            # Get grid point data from NWS
            grid_url = (
                f"https://api.weather.gov/points/{location.latitude},{location.longitude}"
            )
            grid_response = requests.get(grid_url, headers=headers, timeout=10)
            grid_response.raise_for_status()
            grid_data = grid_response.json()

            properties = grid_data.get("properties", {})
            observation_stations_url = properties.get("observationStations")

            if not observation_stations_url:
                logger.warning(f"No observation stations found for {location.name}")
                return None

            # Get observation stations
            stations_response = requests.get(
                observation_stations_url, headers=headers, timeout=10
            )
            stations_response.raise_for_status()
            stations_data = stations_response.json()

            stations = stations_data.get("features", [])
            if not stations:
                logger.warning(f"No stations available for {location.name}")
                return None

            station_id = stations[0].get("properties", {}).get("stationIdentifier")
            if not station_id:
                logger.warning(f"No station ID found for {location.name}")
                return None

            # Get latest observation
            obs_url = f"https://api.weather.gov/stations/{station_id}/observations/latest"
            obs_response = requests.get(obs_url, headers=headers, timeout=10)
            obs_response.raise_for_status()
            obs_data = obs_response.json()

            obs_props = obs_data.get("properties", {})

            # Extract values and convert units
            temp_c = obs_props.get("temperature", {}).get("value")
            temperature = int(temp_c * 9 / 5 + 32) if temp_c else None

            feels_like_c = obs_props.get("apparentTemperature", {}).get("value")
            feels_like = int(feels_like_c * 9 / 5 + 32) if feels_like_c else None

            condition = obs_props.get("textDescription", "Unknown")

            wind_speed_ms = obs_props.get("windSpeed", {}).get("value")
            wind_speed = int(wind_speed_ms * 2.237) if wind_speed_ms else 0  # m/s to mph

            wind_direction = obs_props.get("windDirection", {}).get("value")
            wind_direction_str = CurrentConditionsService._bearing_to_direction(wind_direction)

            wind_gust_ms = obs_props.get("windGust", {}).get("value")
            wind_gust = int(wind_gust_ms * 2.237) if wind_gust_ms else None

            humidity = obs_props.get("relativeHumidity", {}).get("value")
            humidity_val = int(humidity) if humidity else 0

            # Precipitation
            precip_mm = obs_props.get("precipitationLast3Hours", {}).get("value")
            precipitation = precip_mm / 25.4 if precip_mm else None  # mm to inches

            # Advanced metrics
            pressure_pa = obs_props.get("barometricPressure", {}).get("value")
            pressure = pressure_pa / 100 if pressure_pa else None  # Pa to mb

            visibility_m = obs_props.get("visibility", {}).get("value")
            visibility = visibility_m / 1609.34 if visibility_m else None  # meters to miles

            # Create or update CurrentConditions
            current_conditions, created = CurrentConditions.objects.update_or_create(
                location=location,
                defaults={
                    "temperature": temperature or 0,
                    "feels_like_temperature": feels_like,
                    "condition": condition,
                    "wind_speed": wind_speed,
                    "wind_direction": wind_direction_str,
                    "wind_gust": wind_gust,
                    "humidity": humidity_val,
                    "precipitation": precipitation,
                    "pressure": pressure,
                    "visibility": visibility,
                    "uv_index": None,  # TODO: Add UV index from separate source
                    "last_observation_time": timezone.now(),
                    "raw_data": obs_data,
                },
            )

            action = "created" if created else "updated"
            logger.info(f"Successfully {action} current conditions for {location.name}")
            return current_conditions

        except requests.RequestException as e:
            logger.error(f"API request failed for {location.name}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error fetching current conditions for {location.name}: {str(e)}")
            return None

    @staticmethod
    def _bearing_to_direction(bearing):
        """Convert bearing in degrees to cardinal direction."""
        if bearing is None:
            return ""
        bearing = bearing % 360
        directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                      "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        idx = int((bearing + 11.25) / 22.5)
        return directions[idx % 16]


class ForecastService:
    """Service for fetching forecasts with 15-minute cache validation."""

    @staticmethod
    def get_or_fetch_hourly_forecasts(location: Location, force_refresh: bool = False):
        """
        Get hourly forecasts for a location.

        Strategy: Same as CurrentConditionsService - check cache age, fetch if stale.

        Args:
            location: Location instance
            force_refresh: If True, bypass cache

        Returns:
            QuerySet of HourlyForecast objects
        """
        # Get most recent forecast
        recent_forecasts = location.forecasts.filter(
            period_start__gte=timezone.now()
        ).order_by('-last_api_update').first()

        should_fetch = (
            force_refresh or
            recent_forecasts is None or
            recent_forecasts.is_stale
        )

        if should_fetch:
            logger.info(
                f"Fetching fresh hourly forecasts for {location.name} "
                f"(force_refresh={force_refresh}, exists={recent_forecasts is not None}, "
                f"stale={recent_forecasts.is_stale if recent_forecasts else 'N/A'})"
            )
            # TODO: Call API fetch method

        return location.forecasts.filter(
            period_start__gte=timezone.now(),
            hourlyforecast__isnull=False
        ).order_by('period_start')

    @staticmethod
    def get_or_fetch_daily_forecasts(location: Location, force_refresh: bool = False):
        """
        Get daily forecasts for a location.

        Args:
            location: Location instance
            force_refresh: If True, bypass cache

        Returns:
            QuerySet of DailyForecast objects
        """
        # Get most recent forecast
        recent_forecasts = location.forecasts.filter(
            period_start__gte=timezone.now(),
            dailyforecast__isnull=False
        ).order_by('-last_api_update').first()

        should_fetch = (
            force_refresh or
            recent_forecasts is None or
            recent_forecasts.is_stale
        )

        if should_fetch:
            logger.info(
                f"Fetching fresh daily forecasts for {location.name} "
                f"(force_refresh={force_refresh})"
            )
            # TODO: Call API fetch method

        return location.forecasts.filter(
            period_start__gte=timezone.now(),
            dailyforecast__isnull=False
        ).order_by('period_start')
