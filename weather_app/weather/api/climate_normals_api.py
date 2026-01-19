"""API endpoint for fetching and populating climate normals."""

import logging

import requests
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from weather.models import Location

logger = logging.getLogger("weather")


class ClimateNormalsAPIView(APIView):
    """API view to fetch and populate climate normals for a location."""

    permission_classes = []  # Public endpoint

    def get(self, request, *args, **kwargs):
        """Fetch climate normals for a location from NWS and update the database."""
        location_id = request.query_params.get("location_id")

        if not location_id:
            return Response(
                {"error": "location_id parameter is required"}, status=400
            )
        
        # Don't fetch for custom locations (from map picker)
        if location_id == "custom":
            return Response(
                {"error": "Cannot fetch climate normals for custom locations", "status": "custom_location"}, status=400
            )

        try:
            location = get_object_or_404(Location, id=location_id)

            # Check if already populated
            if location.avg_high_temp is not None and location.avg_low_temp is not None:
                return Response(
                    {
                        "status": "cached",
                        "location_id": str(location.id),
                        "avg_high_temp": location.avg_high_temp,
                        "avg_low_temp": location.avg_low_temp,
                    }
                )

            # Fetch from NWS
            avg_high, avg_low = self._fetch_climate_normals(
                float(location.latitude), float(location.longitude)
            )

            if avg_high is not None and avg_low is not None:
                location.avg_high_temp = avg_high
                location.avg_low_temp = avg_low
                location.save(update_fields=["avg_high_temp", "avg_low_temp"])

                return Response(
                    {
                        "status": "success",
                        "location_id": str(location.id),
                        "avg_high_temp": avg_high,
                        "avg_low_temp": avg_low,
                    }
                )
            else:
                return Response(
                    {
                        "status": "error",
                        "error": "Could not fetch climate data from NWS",
                    },
                    status=500,
                )

        except Exception as e:
            logger.error(f"Error fetching climate normals: {str(e)}")
            return Response({"status": "error", "error": str(e)}, status=500)

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
                logger.info(f"Climate normals for {city}, {state}: High={avg_high}°F, Low={avg_low}°F")
                return round(avg_high, 1), round(avg_low, 1)

            return None, None
        except requests.exceptions.RequestException as e:
            logger.error(f"NWS API error: {str(e)}")
            return None, None
