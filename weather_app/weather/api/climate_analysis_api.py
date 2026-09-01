"""API endpoint for persisted historical climate analysis data."""

from __future__ import annotations

from datetime import date

from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from weather.climate_analysis import calculate_pearson_correlation
from weather.models import (
    HistoricalWeatherObservation,
    Location,
    TeleconnectionObservation,
)


class ClimateAnalysisAPIView(APIView):
    """Return aligned local weather and teleconnection observations for a date range."""

    permission_classes = []
    maximum_days = 366
    weather_fields = ("mean_temperature", "precipitation", "wind_speed", "snowfall")

    def get(self, request, *args, **kwargs):
        location_id = request.query_params.get("location_id")
        if not location_id:
            return Response({"error": "location_id parameter is required"}, status=400)

        try:
            start_date = date.fromisoformat(request.query_params["start_date"])
            end_date = date.fromisoformat(request.query_params["end_date"])
        except (KeyError, ValueError):
            return Response(
                {"error": "start_date and end_date must be ISO dates"}, status=400
            )

        if start_date > end_date or (end_date - start_date).days + 1 > self.maximum_days:
            return Response(
                {"error": "date range must be ordered and no longer than 366 days"},
                status=400,
            )

        session_location_ids = {str(item) for item in request.session.get("location_ids", [])}
        if location_id not in session_location_ids:
            return Response({"error": "location is not available in this session"}, status=404)
        location = get_object_or_404(Location, id=location_id)

        index_keys = request.query_params.getlist("index") or list(
            TeleconnectionObservation.IndexKey.values
        )
        unsupported = set(index_keys) - set(TeleconnectionObservation.IndexKey.values)
        if unsupported:
            return Response({"error": "unsupported climate index"}, status=400)

        observations = HistoricalWeatherObservation.objects.filter(
            location=location, observation_date__range=(start_date, end_date)
        ).order_by("observation_date", "source_kind")
        weather_by_date = {}
        for observation in observations:
            existing = weather_by_date.get(observation.observation_date)
            if existing is None or (
                observation.source_kind == HistoricalWeatherObservation.SourceKind.NCEI_STATION
            ):
                weather_by_date[observation.observation_date] = observation

        daily_weather = [self._serialize_weather(observation) for observation in weather_by_date.values()]
        index_observations = TeleconnectionObservation.objects.filter(
            index_key__in=index_keys, observation_date__range=(start_date, end_date)
        ).order_by("index_key", "observation_date")
        indices = self._serialize_indices(index_observations)

        return Response(
            {
                "location_id": str(location.id),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "weather": daily_weather,
                "indices": indices,
                "correlations": self._correlations(indices, weather_by_date),
            }
        )

    def _serialize_weather(self, observation):
        return {
            "date": observation.observation_date.isoformat(),
            "source_kind": observation.source_kind,
            "source_identifier": observation.source_identifier,
            "mean_temperature": observation.mean_temperature,
            "precipitation": observation.precipitation,
            "wind_speed": observation.wind_speed,
            "snowfall": observation.snowfall,
        }

    def _serialize_indices(self, observations):
        return [
            {
                "index": observation.index_key,
                "date": observation.observation_date.isoformat(),
                "value": observation.value,
                "source_url": observation.source_url,
            }
            for observation in observations
        ]

    def _correlations(self, indices, weather_by_date):
        results = []
        for index_key in {item["index"] for item in indices}:
            index_values = {
                date.fromisoformat(item["date"]): item["value"]
                for item in indices
                if item["index"] == index_key
            }
            for field in self.weather_fields:
                result = calculate_pearson_correlation(
                    (
                        (value, getattr(weather_by_date.get(date_key), field, None))
                        for date_key, value in index_values.items()
                    )
                )
                results.append(
                    {
                        "index": index_key,
                        "weather_variable": field,
                        "value": result.value,
                        "sample_count": result.sample_count,
                    }
                )
        return results
