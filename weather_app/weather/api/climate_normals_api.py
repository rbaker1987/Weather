"""API endpoint for 1991-2020 climate normals at a place."""

import logging
from datetime import date

from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from weather.climate_normals import (
    PERIOD,
    ClimateNormalsError,
    fetch_daily_normals,
    normals_for_dates,
)
from weather.place_service import validate_coordinates

logger = logging.getLogger("weather")

DEFAULT_DAYS = 7
MAX_DAYS = 16
SOURCE = "Open-Meteo Archive (ERA5 reanalysis)"


class ClimateNormalsThrottle(AnonRateThrottle):
    # Generous: results are cached, but a cold lookup is one large archive call and
    # the models page asks for normals each time the place changes.
    rate = "120/hour"


class ClimateNormalsAPIView(APIView):
    """GET /api/climate-normals/?lat=&lon=&days=7

    Returns the 1991-2020 average high and low at the place for the next ``days``
    days, as ``avg_high_temp`` / ``avg_low_temp`` plus the daily values.
    """

    permission_classes = []  # Public endpoint
    throttle_classes = [ClimateNormalsThrottle]

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
            days = int(request.query_params.get("days", DEFAULT_DAYS))
        except ValueError:
            days = 0
        if not 1 <= days <= MAX_DAYS:
            return Response(
                {"error": f"days must be between 1 and {MAX_DAYS}"}, status=400
            )

        try:
            normals = fetch_daily_normals(latitude, longitude)
        except ClimateNormalsError as exc:
            logger.warning("Climate normals unavailable: %s", exc)
            return Response(
                {"status": "error", "error": "Climate normals are unavailable"},
                status=502,
            )

        daily = normals_for_dates(normals, date.today(), days)
        highs = [d["high"] for d in daily if d["high"] is not None]
        lows = [d["low"] for d in daily if d["low"] is not None]
        return Response(
            {
                "status": "success",
                "period": PERIOD,
                "source": SOURCE,
                "avg_high_temp": round(sum(highs) / len(highs), 1) if highs else None,
                "avg_low_temp": round(sum(lows) / len(lows), 1) if lows else None,
                "daily": daily,
            }
        )
