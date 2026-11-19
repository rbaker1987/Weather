"""API endpoints for the place page panels, so the page can load each one on its own.

GET /api/place/<panel>/?latitude=&longitude= with panel one of ``current``,
``forecast`` or ``alerts``. Each panel makes its own upstream calls (the NWS grid
lookup is shared through the cache), so one slow or failing upstream never blocks
the others.
"""

import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from weather.place_service import (
    fetch_alerts_panel,
    fetch_current_panel,
    fetch_forecast_panel,
    is_unsupported_place,
    validate_coordinates,
)

logger = logging.getLogger("weather")

PANELS = {
    "current": fetch_current_panel,
    "forecast": fetch_forecast_panel,
    "alerts": fetch_alerts_panel,
}


class PlacePanelAPIView(APIView):
    """One panel of the place page as JSON."""

    permission_classes = []  # Public endpoint

    def get(self, request, panel):
        fetch = PANELS.get(panel)
        if fetch is None:
            return Response(
                {"status": "error", "error": f"Unknown panel '{panel}'"}, status=404
            )
        try:
            lat, lon = validate_coordinates(
                request.query_params.get("latitude"),
                request.query_params.get("longitude"),
            )
        except ValueError:
            return Response(
                {"status": "error", "error": "Valid latitude and longitude required"},
                status=400,
            )

        try:
            data = fetch(lat, lon)
        except Exception as exc:
            # The NWS answers 404 for points outside its US coverage.
            if is_unsupported_place(exc):
                return Response(
                    {
                        "status": "error",
                        "supported": False,
                        "error": "The National Weather Service does not cover this location",
                    },
                    status=404,
                )
            logger.warning("Place panel %s failed: %s", panel, exc)
            return Response(
                {"status": "error", "error": "Weather service unavailable"}, status=502
            )
        return Response({"status": "success", "supported": True, "data": data})
