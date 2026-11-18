"""API endpoint: which forecast models have been most accurate lately."""

import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from weather.forecast_verification import VerificationError, verify_models
from weather.place_service import validate_coordinates

logger = logging.getLogger("weather")


class ForecastVerificationAPIView(APIView):
    """GET /api/forecast-verification/?latitude=&longitude=&models=GFS,ICON"""

    permission_classes = []  # Public endpoint

    def get(self, request):
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
        requested = request.query_params.get("models", "")
        models = [m.strip().upper() for m in requested.split(",") if m.strip()]
        try:
            result = verify_models(lat, lon, models or None)
        except VerificationError as exc:
            return Response({"status": "error", "error": str(exc)}, status=502)
        return Response({"status": "success", **result})
