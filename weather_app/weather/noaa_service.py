"""Service for fetching weather model data from NOAA sources."""

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# NOAA models available via NWS Grid Point API
NOAA_MODELS = {"GFS", "NAM", "HRRR", "NDFD"}


def fetch_noaa_forecast(
    latitude: float,
    longitude: float,
    model: str,
) -> Optional[dict]:
    """
    Fetch weather data from NOAA via NWS Grid Point API.

    Uses the latest available model run automatically.
    Only works for US locations.

    Args:
        latitude: Location latitude
        longitude: Location longitude
        model: Model name (GFS, NAM, HRRR, NDFD)

    Returns:
        Forecast data dict or None if fetch fails
    """
    if model not in NOAA_MODELS:
        logger.debug(f"Model {model} not available via NOAA")
        return None

    try:
        # Step 1: Get grid point metadata
        points_url = f"https://api.weather.gov/points/{latitude},{longitude}"
        points_resp = requests.get(points_url, timeout=10)
        points_resp.raise_for_status()
        points_data = points_resp.json()

        if "properties" not in points_data:
            logger.error(f"No properties in points response: {points_data}")
            return None

        props = points_data["properties"]
        grid_x = props.get("gridX")
        grid_y = props.get("gridY")
        office = props.get("cwa")

        if not all([grid_x, grid_y, office]):
            logger.error(
                f"Missing grid data: gridX={grid_x}, gridY={grid_y}, cwa={office}"
            )
            return None

        logger.debug(f"Got grid point: office={office}, gridX={grid_x}, gridY={grid_y}")

        # Step 2: Map model to NOAA grid data endpoint
        if model == "GFS":
            # GFS via /gridpoints/office/gridX,gridY/forecast
            forecast_url = f"https://api.weather.gov/gridpoints/{office}/{grid_x},{grid_y}/forecast"
        elif model == "NAM":
            # NAM via /gridpoints/office/gridX,gridY/forecast
            forecast_url = f"https://api.weather.gov/gridpoints/{office}/{grid_x},{grid_y}/forecast"
        elif model == "HRRR":
            # HRRR via /gridpoints/office/gridX,gridY/forecast
            forecast_url = f"https://api.weather.gov/gridpoints/{office}/{grid_x},{grid_y}/forecast"
        elif model == "NDFD":
            # NDFD via /gridpoints/office/gridX,gridY/forecast
            forecast_url = f"https://api.weather.gov/gridpoints/{office}/{grid_x},{grid_y}/forecast"
        else:
            logger.warning(f"No forecast endpoint mapping for model {model}")
            return None

        # Step 3: Fetch forecast
        forecast_resp = requests.get(forecast_url, timeout=10)
        forecast_resp.raise_for_status()
        forecast_data = forecast_resp.json()

        if "properties" not in forecast_data:
            logger.error("No properties in forecast response")
            return None

        # Extract hourly data from periods (NWS provides 12-hour periods, not hourly)
        periods = forecast_data.get("properties", {}).get("periods", [])

        if not periods:
            logger.warning("No forecast periods found")
            return None

        # Convert NWS format to hourly format similar to Open-Meteo
        hourly_data = _convert_nws_to_hourly(periods)

        # Get generation time from response
        generation_time = forecast_data.get("properties", {}).get(
            "generatedAt", datetime.now(timezone.utc).isoformat()
        )

        return {
            "latitude": latitude,
            "longitude": longitude,
            "elevation": props.get("elevation", {}).get("value", 0),
            "hourly": hourly_data,
            "generation_time": generation_time,
            "model_source": "NOAA",
            "grid_point": {"office": office, "x": grid_x, "y": grid_y},
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch NOAA forecast for {model}: {e}")
        return None
    except (KeyError, ValueError) as e:
        logger.error(f"Failed to parse NOAA response for {model}: {e}")
        return None


def _convert_nws_to_hourly(periods: list) -> dict:
    """
    Convert NWS periods (12-hour) to hourly format.

    This is a simplified conversion since NWS provides period forecasts.
    For a full solution, you'd need to use NOAA's GridData API.

    Args:
        periods: List of forecast periods from NWS

    Returns:
        Dict with hourly arrays
    """
    times = []
    temps = []
    humidity = []
    wind_speed = []
    precipitation = []

    for period in periods:
        # Use the start time and estimate hourly values
        start_time = period.get("startTime", "")
        if start_time:
            times.append(start_time)

        # Extract temperature
        temp = period.get("temperature")
        if temp is not None:
            temps.append(temp)

        # Extract relative humidity
        rh = period.get("relativeHumidity", {})
        if isinstance(rh, dict):
            humidity.append(rh.get("value"))
        else:
            humidity.append(rh)

        # Extract wind speed
        wind = period.get("windSpeed", "")
        if wind:
            # Parse "10 mph" format
            try:
                wind_mph = int(wind.split()[0])
                wind_speed.append(wind_mph)
            except (ValueError, IndexError):
                wind_speed.append(None)

        # NWS doesn't provide hourly precipitation in periods
        precipitation.append(None)

    return {
        "time": times,
        "temperature_2m": temps,
        "relativehumidity_2m": humidity,
        "wind_speed_10m": wind_speed,
        "precipitation": precipitation,
    }
