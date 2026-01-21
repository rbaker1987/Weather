"""Modern asynchronous NWS API client with error handling and rate limiting."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from loguru import logger

from ..core.config import get_config
from ..core.models import (
    DailyForecast,
    HourlyForecast,
    Location,
    Temperature,
    WeatherAlert,
    WeatherCondition,
    WindCondition,
)


class NWSAPIError(Exception):
    """Base exception for NWS API errors."""


class LocationNotFoundError(NWSAPIError):
    """Raised when a location cannot be geocoded."""


class ForecastNotAvailableError(NWSAPIError):
    """Raised when forecast data is not available for a location."""


class RateLimitError(NWSAPIError):
    """Raised when API rate limit is exceeded."""


class NWSClient:
    """Modern asynchronous client for the National Weather Service API."""

    def __init__(self):
        self.config = get_config().api
        self.base_url = self.config.nws_base_url
        self.timeout = self.config.request_timeout
        self.rate_limit_delay = self.config.rate_limit_delay
        self.user_agent = self.config.user_agent
        self._last_request_time = 0.0
        self._client: Optional[httpx.AsyncClient] = None

    @asynccontextmanager
    async def _get_client(self):
        """Get HTTP client with proper configuration."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            )
        try:
            yield self._client
        finally:
            # Keep client open for reuse
            pass

    async def _rate_limit(self):
        """Implement rate limiting to be respectful to the NWS API."""
        current_time = asyncio.get_event_loop().time()
        time_since_last_request = current_time - self._last_request_time

        if time_since_last_request < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - time_since_last_request)

        self._last_request_time = asyncio.get_event_loop().time()

    async def _make_request(
        self, url: str, params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Make a rate-limited HTTP request to the NWS API."""
        await self._rate_limit()

        try:
            async with self._get_client() as client:
                logger.debug(f"Making request to: {url}")
                response = await client.get(url, params=params)
                response.raise_for_status()

                data = response.json()

                # Handle NWS API specific errors
                if "status" in data and data["status"] >= 400:
                    if data["status"] == 404:
                        raise LocationNotFoundError(f"Location not found: {url}")
                    if data["status"] == 429:
                        raise RateLimitError("API rate limit exceeded")
                    raise NWSAPIError(
                        f"API error {data['status']}: {data.get('title', 'Unknown error')}"
                    )

                return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise LocationNotFoundError(f"Endpoint not found: {url}")
            if e.response.status_code == 429:
                raise RateLimitError("API rate limit exceeded")
            raise NWSAPIError(f"HTTP {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise NWSAPIError(f"Request failed: {str(e)}")

    async def get_grid_point(self, lat: float, lon: float) -> dict[str, Any]:
        """Get NWS grid point information for coordinates."""
        url = f"{self.base_url}/points/{lat},{lon}"
        return await self._make_request(url)

    async def get_forecast_grid_data(self, wfo: str, x: int, y: int) -> dict[str, Any]:
        """Get detailed forecast grid data."""
        url = f"{self.base_url}/gridpoints/{wfo}/{x},{y}"
        return await self._make_request(url)

    async def get_hourly_forecast(self, wfo: str, x: int, y: int) -> dict[str, Any]:
        """Get hourly forecast data."""
        url = f"{self.base_url}/gridpoints/{wfo}/{x},{y}/forecast/hourly"
        return await self._make_request(url)

    async def get_alerts_for_point(
        self, lat: float, lon: float
    ) -> list[dict[str, Any]]:
        """Get active weather alerts for a point."""
        url = f"{self.base_url}/alerts/active"
        params = {"point": f"{lat},{lon}"}

        try:
            data = await self._make_request(url, params)
            return data.get("features", [])
        except Exception as e:
            logger.warning(f"Failed to get alerts for {lat},{lon}: {e}")
            return []

    async def get_forecast_for_location(
        self, location: Location
    ) -> list[HourlyForecast]:
        """Get complete forecast data for a location."""
        if location.latitude is None or location.longitude is None:
            raise ValueError(f"Location {location.name} must have coordinates")

        try:
            # Get grid point information
            grid_data = await self.get_grid_point(location.latitude, location.longitude)
            properties = grid_data["properties"]

            wfo = properties["cwa"]
            grid_x = properties["gridX"]
            grid_y = properties["gridY"]

            # Get hourly forecast
            hourly_data = await self.get_hourly_forecast(wfo, grid_x, grid_y)
            periods = hourly_data["properties"]["periods"]

            # Get alerts
            alerts_data = await self.get_alerts_for_point(
                location.latitude, location.longitude
            )
            alerts = [self._parse_alert(alert_data) for alert_data in alerts_data]

            # Parse forecast periods into our models
            forecasts = []
            for period in periods:
                forecast = self._parse_hourly_period(period, location, alerts)
                forecasts.append(forecast)

            return forecasts[:192]  # Limit to 8 days (192 hours)

        except Exception as e:
            logger.error(f"Failed to get forecast for {location.name}: {e}")
            raise ForecastNotAvailableError(
                f"Forecast not available for {location.name}: {str(e)}"
            )

    def _parse_hourly_period(
        self, period: dict[str, Any], location: Location, alerts: list[WeatherAlert]
    ) -> HourlyForecast:
        """Parse a single hourly forecast period."""
        start_time = datetime.fromisoformat(period["startTime"].replace("Z", "+00:00"))

        # Extract temperature
        temp_value = period["temperature"]
        temp_unit = period["temperatureUnit"]
        if temp_unit == "C":
            temp_value = int(temp_value * 9 / 5 + 32)  # Convert to Fahrenheit

        # Extract wind data
        wind_speed = 0
        wind_direction = None
        if period.get("windSpeed"):
            wind_parts = period["windSpeed"].split()
            if wind_parts:
                try:
                    wind_speed = int(wind_parts[0])
                except (ValueError, IndexError):
                    wind_speed = 0

        if period.get("windDirection"):
            wind_direction = period["windDirection"]

        # Find relevant alerts for this time period
        relevant_alerts = [
            alert
            for alert in alerts
            if alert.start_time
            <= start_time
            <= (alert.end_time or start_time + timedelta(hours=1))
        ]

        # Wind gust
        wind_gust = None
        gust_str = period.get("windGust")
        if gust_str:
            gust_parts = gust_str.split()
            if gust_parts:
                try:
                    wind_gust = int(gust_parts[0])
                except (ValueError, IndexError):
                    wind_gust = None

        # Precipitation probability
        precip_prob = None
        pop = period.get("probabilityOfPrecipitation")
        if isinstance(pop, dict):
            value = pop.get("value")
            if value is not None:
                try:
                    precip_prob = int(value)
                except (ValueError, TypeError):
                    precip_prob = None

        return HourlyForecast(
            location=location,
            forecast_time=start_time,
            temperature=Temperature(value=temp_value),
            wind=WindCondition(
                speed=wind_speed, direction=wind_direction, gust=wind_gust
            ),
            weather=WeatherCondition(
                short_forecast=period.get("shortForecast", "Unknown"),
                detailed_forecast=period.get("detailedForecast"),
                icon_url=period.get("icon"),
            ),
            alerts=relevant_alerts,
            precipitation_probability=precip_prob,
        )

    def _parse_alert(self, alert_data: dict[str, Any]) -> WeatherAlert:
        """Parse NWS alert data into our model."""
        properties = alert_data["properties"]

        start_time = datetime.fromisoformat(
            properties.get("onset", properties.get("sent", ""))
        )
        end_time = None
        if properties.get("ends"):
            end_time = datetime.fromisoformat(properties["ends"])

        return WeatherAlert(
            event=properties.get("event", "Unknown"),
            headline=properties.get("headline"),
            description=properties.get("description"),
            start_time=start_time,
            end_time=end_time,
            severity=properties.get("severity"),
        )

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


class WeatherService:
    """High-level weather service that orchestrates data retrieval."""

    def __init__(self):
        self.nws_client = NWSClient()

    async def get_forecasts_for_locations(
        self, locations: list[Location]
    ) -> dict[str, list[HourlyForecast]]:
        """Get forecasts for multiple locations."""
        results = {}
        failed_locations = []

        for location in locations:
            try:
                forecasts = await self.nws_client.get_forecast_for_location(location)
                results[location.name] = forecasts
                logger.info(f"Successfully retrieved forecast for {location.name}")
            except Exception as e:
                logger.error(f"Failed to get forecast for {location.name}: {e}")
                failed_locations.append((location.name, str(e)))
                results[location.name] = []

        if failed_locations:
            logger.warning(
                f"Failed to get forecasts for {len(failed_locations)} locations"
            )

        return results

    def group_hourly_into_daily(
        self, hourly_forecasts: list[HourlyForecast]
    ) -> list[DailyForecast]:
        """Group hourly forecasts into daily forecasts."""
        if not hourly_forecasts:
            return []

        # Group by date
        daily_groups = {}
        for forecast in hourly_forecasts:
            date_key = forecast.forecast_time.date()
            if date_key not in daily_groups:
                daily_groups[date_key] = []
            daily_groups[date_key].append(forecast)

        # Create daily forecasts
        daily_forecasts = []
        for date_key, hourly_list in sorted(daily_groups.items()):
            if hourly_list:  # Ensure we have data
                daily_forecast = DailyForecast(
                    date=date_key,
                    location=hourly_list[0].location,
                    hourly_forecasts=hourly_list,
                )
                daily_forecasts.append(daily_forecast)

        return daily_forecasts

    async def close(self):
        """Close all resources."""
        await self.nws_client.close()
