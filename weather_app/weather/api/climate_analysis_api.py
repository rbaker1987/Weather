"""API endpoint for persisted historical climate analysis data."""

from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta

from django.core.management.base import CommandError
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from weather.climate_analysis import calculate_pearson_correlation
from weather.management.commands.import_climate_data import (
    Command as ImportClimateDataCommand,
)
from weather.models import (
    HistoricalWeatherObservation,
    Location,
    TeleconnectionObservation,
)

logger = logging.getLogger("weather")


class ClimateAnalysisAPIView(APIView):
    """Return smoothed weekly observations centered on a calendar day."""

    permission_classes = []
    first_year = 1950
    window_days = 7
    weather_fields = ("mean_temperature", "precipitation", "wind_speed", "snowfall")
    supported_index_keys = ("nao", "ao", "pna", "oni", "epo")

    def get(self, request, *args, **kwargs):
        location_id = request.query_params.get("location_id")
        if not location_id:
            return Response({"error": "location_id parameter is required"}, status=400)

        try:
            month = int(request.query_params["month"])
            day = int(request.query_params["day"])
            calendar.monthrange(2000, month)[1]
            date(2000, month, day)
        except (KeyError, TypeError, ValueError):
            return Response({"error": "month and day must be a valid calendar date"}, status=400)

        index_keys = request.query_params.getlist("index") or list(
            self.supported_index_keys
        )
        unsupported = set(index_keys) - set(self.supported_index_keys)
        if unsupported:
            return Response({"error": "unsupported climate index"}, status=400)

        session_location_ids = {str(item) for item in request.session.get("location_ids", [])}
        if location_id not in session_location_ids:
            return Response({"error": "location is not available in this session"}, status=404)
        location = get_object_or_404(Location, id=location_id)

        # Use completed years only so every sample has a complete centered window.
        last_year = date.today().year - 1
        years = [
            year
            for year in range(self.first_year + 1, last_year)
            if not (month == 2 and day == 29 and not calendar.isleap(year))
        ]
        calendar_dates = [date(year, month, day) for year in years]
        half_window = self.window_days // 2

        required_dates = {
            window_date
            for calendar_date in calendar_dates
            for window_date in self._window_dates(calendar_date)
        }
        weather_queryset = HistoricalWeatherObservation.objects.filter(
            location=location, observation_date__in=required_dates
        )
        weather_loaded = False
        existing_weather_dates = set(weather_queryset.values_list("observation_date", flat=True))
        missing_weather_years = []
        for year, calendar_date in zip(years, calendar_dates, strict=True):
            window_dates = self._window_dates(calendar_date)
            if any(window_date not in existing_weather_dates for window_date in window_dates):
                missing_weather_years.append(year)
        if missing_weather_years:
            try:
                importer = ImportClimateDataCommand()
                first_window = date(min(missing_weather_years), month, day)
                last_window = date(max(missing_weather_years), month, day)
                importer._import_weather(
                    location,
                    first_window - timedelta(days=half_window),
                    last_window + timedelta(days=half_window),
                )
            except CommandError:
                logger.exception("Historical weather data loading failed")
                return Response(
                    {"error": "historical weather data could not be loaded"},
                    status=502,
                )
            weather_loaded = True

        supported_index_keys = set(index_keys)
        available_index_count = TeleconnectionObservation.objects.filter(
            index_key__in=supported_index_keys,
            observation_date__month=month,
            observation_date__day=day,
            observation_date__year__in=years,
        ).values("index_key", "observation_date").distinct().count()
        index_loaded = False
        if available_index_count < len(years) * len(supported_index_keys):
            try:
                index_loaded = ImportClimateDataCommand().import_noaa_calendar_day(
                    month, day, set(missing_weather_years) | set(years), index_keys
                ) > 0
            except CommandError:
                logger.exception("Climate index data loading failed")
                return Response(
                    {"error": "climate index data could not be loaded"},
                    status=502,
                )

        observations = HistoricalWeatherObservation.objects.filter(
            location=location, observation_date__in=required_dates
        ).order_by("observation_date", "source_kind")
        weather_by_date = {}
        for observation in observations:
            existing = weather_by_date.get(observation.observation_date)
            if existing is None or (
                observation.source_kind == HistoricalWeatherObservation.SourceKind.NCEI_STATION
            ):
                weather_by_date[observation.observation_date] = observation

        weekly_weather = self._weekly_weather(weather_by_date, years, month, day)
        daily_weather = [self._serialize_weather(observation) for observation in weekly_weather.values()]
        index_observations = TeleconnectionObservation.objects.filter(
            index_key__in=index_keys,
            observation_date__month=month,
            observation_date__day=day,
            observation_date__year__in=years,
        ).order_by("index_key", "observation_date")
        indices = self._serialize_indices(index_observations)

        correlations = self._correlations(indices, weekly_weather)
        event_correlations, event_thresholds = self._event_correlations(
            indices, weekly_weather
        )
        return Response(
            {
                "location_id": str(location.id),
                "calendar_day": f"{month:02d}-{day:02d}",
                "window_days": self.window_days,
                "year_count": len(weekly_weather),
                "sample_count": len(weekly_weather),
                "weather": daily_weather,
                "indices": indices,
                "correlations": correlations,
                "event_correlations": event_correlations,
                "event_thresholds": event_thresholds,
                "weather_loaded": weather_loaded,
                "index_loaded": index_loaded,
                "indexes_available": bool(indices),
            }
        )

    def _serialize_weather(self, observation):
        if isinstance(observation, dict):
            return observation
        return {
            "date": observation.observation_date.isoformat(),
            "source_kind": observation.source_kind,
            "source_identifier": observation.source_identifier,
            "mean_temperature": observation.mean_temperature,
            "precipitation": observation.precipitation,
            "wind_speed": observation.wind_speed,
            "snowfall": observation.snowfall,
        }

    def _weekly_weather(self, weather_by_date, years, month, day):
        weekly = {}
        half_window = self.window_days // 2
        for year in years:
            center = date(year, month, day)
            window_dates = [
                center + timedelta(days=offset)
                for offset in range(-half_window, half_window + 1)
            ]
            rows = [weather_by_date.get(item) for item in window_dates]
            if len(rows) != self.window_days or any(row is None for row in rows):
                continue
            values = {}
            for field in self.weather_fields:
                field_values = [getattr(row, field) for row in rows if getattr(row, field) is not None]
                values[field] = sum(field_values) / len(field_values) if field_values else None
            weekly[center] = {
                "date": center.isoformat(),
                "source_kind": "weekly_average",
                "source_identifier": f"{self.window_days}-day centered average",
                **values,
            }
        return weekly

    def _window_dates(self, center):
        half_window = self.window_days // 2
        return [
            center + timedelta(days=offset)
            for offset in range(-half_window, half_window + 1)
        ]

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
                        (value, self._weather_value(weather_by_date.get(date_key), field))
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

    def _event_correlations(self, indices, weekly_weather):
        event_definitions = {
            "warm": ("mean_temperature", "high"),
            "cool": ("mean_temperature", "low"),
            "dry": ("precipitation", "low"),
            "wet": ("precipitation", "high"),
        }
        thresholds = {}
        events_by_year = {}
        for event_name, (field, direction) in event_definitions.items():
            values = [
                item[field]
                for item in weekly_weather.values()
                if item.get(field) is not None
            ]
            if len(values) < 5:
                continue
            ordered = sorted(values)
            threshold_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.9) - 1))
            threshold = ordered[threshold_index] if direction == "high" else ordered[len(ordered) - 1 - threshold_index]
            thresholds[event_name] = round(threshold, 2)
            for center, item in weekly_weather.items():
                value = item.get(field)
                if value is None:
                    continue
                events_by_year.setdefault(event_name, {})[center.year] = (
                    value >= threshold if direction == "high" else value <= threshold
                )

        results = []
        centers_by_year = {center.year: center for center in weekly_weather}
        for index_key in {item["index"] for item in indices}:
            index_values = {
                date.fromisoformat(item["date"]): item["value"]
                for item in indices
                if item["index"] == index_key
            }
            for event_name, year_events in events_by_year.items():
                pairs = [
                    (index_values[center], float(is_event))
                    for year, is_event in year_events.items()
                    for center in [centers_by_year.get(year)]
                    if center in index_values
                ]
                result = calculate_pearson_correlation(pairs)
                results.append(
                    {
                        "index": index_key,
                        "event": event_name,
                        "value": result.value,
                        "sample_count": result.sample_count,
                        "event_count": sum(1 for is_event in year_events.values() if is_event),
                    }
                )
        return results, thresholds

    @staticmethod
    def _weather_value(observation, field):
        if observation is None:
            return None
        if isinstance(observation, dict):
            return observation.get(field)
        return getattr(observation, field, None)
