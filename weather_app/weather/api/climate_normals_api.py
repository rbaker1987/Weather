"""API endpoint for the average high/low of the NWS forecast at a place."""

import logging

import requests
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.views import APIView

from weather.place_service import validate_coordinates

logger = logging.getLogger("weather")

NORMALS_CACHE_SECONDS = 6 * 60 * 60


class ClimateNormalsAPIView(APIView):
    """API view returning average high/low temperatures for coordinates."""

    permission_classes = []  # Public endpoint

    def get(self, request, *args, **kwargs):
        """Fetch average high/low for ``?lat=&lon=`` from NWS, cached in memory."""
        try:
            latitude, longitude = validate_coordinates(
                request.query_params.get("lat"), request.query_params.get("lon")
            )
        except ValueError:
            return Response(
                {"error": "lat and lon must be valid coordinates"}, status=400
            )

        cache_key = f"climate-normals:{latitude:.2f}:{longitude:.2f}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response({"status": "cached", **cached})

        avg_high, avg_low = self._fetch_climate_normals(latitude, longitude)
        if avg_high is None or avg_low is None:
            return Response(
                {
                    "status": "error",
                    "error": "Could not fetch climate data from NWS",
                },
                status=500,
            )
        values = {"avg_high_temp": avg_high, "avg_low_temp": avg_low}
        cache.set(cache_key, values, NORMALS_CACHE_SECONDS)
        return Response({"status": "success", **values})

    def _fetch_climate_normals(self, latitude, longitude):
        """
        Fetch climate normals from NWS/NOAA API by finding the nearest location.
        Returns (avg_high_temp, avg_low_temp) or (None, None) if failed.
        """
        try:
            # First, get the gridpoint from NWS API to find the nearest location
            points_url = f"https://api.weather.gov/points/{latitude},{longitude}"
            points_response = requests.get(points_url, timeout=10)
            points_response.raise_for_status()
            points_data = points_response.json()

            if "properties" not in points_data:
                return None, None

            properties = points_data["properties"]

            # Get the relative location info which gives us the nearest city
            relative_location = properties.get("relativeLocation", {})
            if not relative_location or not relative_location.get("properties"):
                return None, None

            rel_props = relative_location["properties"]
            city = rel_props.get("city")
            state = rel_props.get("state")

            if not city or not state:
                return None, None

            logger.info(f"Found nearest location: {city}, {state}")

            # Get the forecast grid point
            forecast_url = properties.get("forecast")
            if not forecast_url:
                return None, None

            # Fetch the forecast data for this location
            forecast_response = requests.get(forecast_url, timeout=10)
            forecast_response.raise_for_status()
            forecast_data = forecast_response.json()

            if "properties" not in forecast_data:
                return None, None

            forecast_props = forecast_data["properties"]
            periods = forecast_props.get("periods", [])

            if not periods:
                return None, None

            # Calculate averages from forecast data (daytime highs and nighttime lows)
            highs = []
            lows = []

            for period in periods:
                if period.get("isDaytime"):
                    temp = period.get("temperature")
                    if temp is not None:
                        highs.append(temp)
                else:
                    temp = period.get("temperature")
                    if temp is not None:
                        lows.append(temp)

            if highs and lows:
                avg_high = sum(highs) / len(highs)
                avg_low = sum(lows) / len(lows)
                logger.info(
                    f"Climate normals for {city}, {state}: High={avg_high}°F, Low={avg_low}°F"
                )
                return round(avg_high, 1), round(avg_low, 1)

            return None, None
        except requests.exceptions.RequestException as e:
            logger.error(f"NWS API error: {str(e)}")
            return None, None
