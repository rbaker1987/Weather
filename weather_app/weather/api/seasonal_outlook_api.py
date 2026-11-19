"""API endpoint for the seasonal analog outlook (ENSO-based, low skill)."""

import logging
from datetime import date

from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from weather.climate_data import ClimateDataError, fetch_index_series
from weather.place_service import validate_coordinates
from weather.seasonal_outlook import OutlookError, build_outlook, fetch_monthly_weather

logger = logging.getLogger("weather")


class SeasonalOutlookThrottle(AnonRateThrottle):
    scope = "seasonal_outlook"  # its own bucket, separate from the other climate limits
    rate = "10/hour"


class SeasonalOutlookAPIView(APIView):
    """GET /api/seasonal-outlook/?lat=&lon="""

    permission_classes = []  # Public endpoint
    throttle_classes = [SeasonalOutlookThrottle]

    def get(self, request, *args, **kwargs):
        try:
            latitude, longitude = validate_coordinates(
                request.query_params.get("lat"), request.query_params.get("lon")
            )
        except ValueError:
            return Response(
                {"error": "lat and lon must be valid coordinates"}, status=400
            )

        try:
            oni = fetch_index_series("oni")
            monthly = fetch_monthly_weather(latitude, longitude)
            outlook = build_outlook(oni, monthly, date.today())
        except (ClimateDataError, OutlookError) as exc:
            logger.warning("Seasonal outlook unavailable: %s", exc)
            return Response(
                {"status": "error", "error": "The seasonal outlook is unavailable"},
                status=502,
            )
        return Response({"status": "success", **outlook})
