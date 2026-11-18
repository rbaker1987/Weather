"""API endpoint: how much the forecast models agree, day by day."""

import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from weather.api.model_comparison_api import ModelComparisonAPIView
from weather.model_spread import summarize_spread
from weather.place_service import validate_coordinates

logger = logging.getLogger("weather")

MAX_FORECAST_DAYS = 16


class ModelSpreadAPIView(APIView):
    """GET /api/model-spread/?latitude=&longitude=&models=GFS,ICON&forecast_days=7"""

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

        try:
            forecast_days = int(request.query_params.get("forecast_days", "7"))
        except ValueError:
            forecast_days = 0
        if not 1 <= forecast_days <= MAX_FORECAST_DAYS:
            return Response(
                {"status": "error", "error": "forecast_days must be between 1 and 16"},
                status=400,
            )

        configured = ModelComparisonAPIView.MODEL_CONFIGS
        requested = request.query_params.get("models", "")
        models = [m.strip().upper() for m in requested.split(",") if m.strip()]
        models = [m for m in models if m in configured] or list(configured)

        results = ModelComparisonAPIView().fetch_all_models(
            models, lat, lon, forecast_days
        )
        return Response({"status": "success", **summarize_spread(results)})
