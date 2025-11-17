"""Geocoding utilities using modern async approach."""

import asyncio
from typing import Optional, Tuple
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from loguru import logger

from ..core.models import Location


class GeocodingError(Exception):
    """Base exception for geocoding errors."""
    pass


class AsyncGeocoder:
    """Asynchronous geocoding service with retry logic."""
    
    def __init__(self, user_agent: str = "weather-app/0.2.0"):
        self.geocoder = Nominatim(user_agent=user_agent)
        self.max_retries = 3
        self.base_delay = 1.0  # Base delay between retries
    
    async def _run_in_executor(self, func, *args):
        """Run blocking geocoding function in executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, func, *args)
    
    async def geocode_with_retry(self, location_string: str) -> Optional[Tuple[float, float]]:
        """Geocode a location string with exponential backoff retry."""
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Geocoding attempt {attempt + 1} for: {location_string}")
                
                result = await self._run_in_executor(
                    self.geocoder.geocode, 
                    location_string
                )
                
                if result:
                    logger.info(f"Successfully geocoded {location_string}")
                    return (float(result.latitude), float(result.longitude))
                else:
                    logger.warning(f"No geocoding result for: {location_string}")
                    return None
                    
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                if attempt < self.max_retries - 1:
                    delay = self.base_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Geocoding attempt {attempt + 1} failed: {e}. Retrying in {delay}s")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Geocoding failed after {self.max_retries} attempts: {e}")
                    raise GeocodingError(f"Failed to geocode {location_string}: {e}")
            except Exception as e:
                logger.error(f"Unexpected geocoding error for {location_string}: {e}")
                raise GeocodingError(f"Unexpected geocoding error: {e}")
        
        return None
    
    async def reverse_geocode(self, lat: float, lon: float) -> Optional[str]:
        """Reverse geocode coordinates to get address."""
        try:
            result = await self._run_in_executor(
                self.geocoder.reverse,
                (lat, lon)
            )
            
            if result:
                return result.address
            return None
            
        except Exception as e:
            logger.error(f"Reverse geocoding failed for {lat}, {lon}: {e}")
            return None
    
    async def enrich_location(self, location: Location) -> Location:
        """Enrich a location with missing coordinate or address data."""
        if location.latitude is None or location.longitude is None:
            # Need to geocode the name
            coords = await self.geocode_with_retry(location.name)
            if coords:
                location.latitude = coords[0]
                location.longitude = coords[1]
                logger.info(f"Added coordinates to {location.name}: {coords}")
            else:
                logger.warning(f"Could not geocode location: {location.name}")
        
        return location


async def create_location_from_string(location_string: str) -> Location:
    """Create a Location object from a string, with geocoding."""
    geocoder = AsyncGeocoder()
    
    # First try to parse as coordinates
    if "," in location_string:
        parts = location_string.split(",")
        if len(parts) == 2:
            try:
                lat = float(parts[0].strip())
                lon = float(parts[1].strip())
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    # This looks like coordinates
                    address = await geocoder.reverse_geocode(lat, lon)
                    return Location(
                        name=address if address else f"{lat}, {lon}",
                        latitude=lat,
                        longitude=lon
                    )
            except ValueError:
                pass  # Not coordinates, treat as place name
    
    # Create location and enrich with coordinates
    location = Location(name=location_string.strip())
    return await geocoder.enrich_location(location)


async def bulk_geocode_locations(location_strings: list[str]) -> list[Location]:
    """Geocode multiple locations concurrently."""
    tasks = [create_location_from_string(loc_str) for loc_str in location_strings]
    return await asyncio.gather(*tasks, return_exceptions=False)