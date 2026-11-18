"""API endpoint for historical climate analysis computed on demand."""

from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta
from math import ceil

from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from weather.climate_analysis import (
    calculate_pearson_correlation,
    calculate_spearman_correlation,
    correlation_significance,
    detrend_by_year,
)
from weather.climate_data import (
    INDEX_KEYS,
    ClimateDataError,
    fetch_index_series_many,
    fetch_weather_window,
    latest_index_values,
)
from weather.place_service import validate_coordinates

logger = logging.getLogger("weather")


class ClimateAnalysisThrottle(AnonRateThrottle):
    rate = "10/hour"


class ClimateIndicesAPIView(APIView):
    """Return the latest published value of each teleconnection index."""

    permission_classes = []
    throttle_classes = [ClimateAnalysisThrottle]

    def get(self, request, *args, **kwargs):
        latest, unavailable = latest_index_values()
        return Response({"indices": latest, "unavailable_indices": unavailable})


class ClimateAnalysisAPIView(APIView):
    """Return smoothed weekly observations centered on a calendar day."""

    permission_classes = []
    throttle_classes = [ClimateAnalysisThrottle]
    first_year = 1950
    window_days = 7
    weather_fields = ("mean_temperature", "precipitation", "wind_speed", "snowfall")
    supported_index_keys = INDEX_KEYS

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
            month = int(request.query_params["month"])
            day = int(request.query_params["day"])
            calendar.monthrange(2000, month)[1]
            date(2000, month, day)
        except (KeyError, TypeError, ValueError):
            return Response(
                {"error": "month and day must be a valid calendar date"}, status=400
            )

        index_keys = [
            index.strip().lower() for index in request.query_params.getlist("index")
        ] or list(self.supported_index_keys)
        unsupported = set(index_keys) - set(self.supported_index_keys)
        if unsupported:
            return Response({"error": "unsupported climate index"}, status=400)

        # Use completed years only so every sample has a complete centered window.
        last_year = date.today().year - 1
        years = [
            year
            for year in range(self.first_year + 1, last_year + 1)
            if not (month == 2 and day == 29 and not calendar.isleap(year))
        ]
        half_window = self.window_days // 2

        try:
            weather_by_date = fetch_weather_window(
                latitude,
                longitude,
                month,
                day,
                self.first_year + 1,
                last_year,
                half_window,
            )
        except ClimateDataError:
            logger.exception("Historical weather data loading failed")
            return Response(
                {"error": "historical weather data could not be loaded"}, status=502
            )

        series, index_errors = fetch_index_series_many(index_keys)
        if not series:
            logger.error("Climate index data loading failed: %s", index_errors)
            return Response(
                {"error": "climate index data could not be loaded"}, status=502
            )

        weekly_weather = self._weekly_weather(weather_by_date, years, month, day)
        daily_weather = [
            self._serialize_weather(observation)
            for observation in weekly_weather.values()
        ]
        indices = self._window_mean_indices(series, years, month, day)

        correlations = self._correlations(indices, weekly_weather)
        event_correlations, event_thresholds = self._event_correlations(
            indices, weekly_weather
        )
        return Response(
            {
                "latitude": latitude,
                "longitude": longitude,
                "calendar_day": f"{month:02d}-{day:02d}",
                "window_days": self.window_days,
                "year_count": len(weekly_weather),
                "sample_count": len(weekly_weather),
                "weather": daily_weather,
                "indices": indices,
                "correlations": correlations,
                "event_correlations": event_correlations,
                "event_thresholds": event_thresholds,
                "unavailable_indices": sorted(index_errors),
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
                field_values = [
                    getattr(row, field)
                    for row in rows
                    if getattr(row, field) is not None
                ]
                values[field] = (
                    sum(field_values) / len(field_values) if field_values else None
                )
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

    def _window_mean_indices(self, series_by_key, years, month, day):
        """Average each index over the same centered window used for weather."""
        results = []
        for index_key in sorted(series_by_key):
            series = series_by_key[index_key]
            for year in years:
                center = date(year, month, day)
                if series.value_on(center) is None:
                    continue
                window = [
                    value
                    for value in (
                        series.value_on(item) for item in self._window_dates(center)
                    )
                    if value is not None
                ]
                if not window:
                    continue
                results.append(
                    {
                        "index": index_key,
                        "date": center.isoformat(),
                        "value": sum(window) / len(window),
                        "days_averaged": len(window),
                        "cadence": series.cadence,
                        "source_url": series.url,
                    }
                )
        return results

    def _correlations(self, indices, weather_by_date):
        results = []
        for index_key in sorted({item["index"] for item in indices}):
            index_values = {
                date.fromisoformat(item["date"]): item["value"]
                for item in indices
                if item["index"] == index_key
            }
            for field in self.weather_fields:
                pairs = [
                    (value, self._weather_value(weather_by_date.get(date_key), field))
                    for date_key, value in index_values.items()
                ]
                result = calculate_pearson_correlation(pairs)
                spearman = calculate_spearman_correlation(pairs)
                detrended = calculate_pearson_correlation(
                    detrend_by_year(
                        (x, y, date_key.year)
                        for date_key, (x, y) in zip(index_values, pairs, strict=True)
                    )
                )
                significance = correlation_significance(
                    result.value, result.sample_count
                )
                results.append(
                    {
                        "index": index_key,
                        "weather_variable": field,
                        "value": result.value,
                        "sample_count": result.sample_count,
                        "r_squared": None if result.value is None else result.value**2,
                        "spearman": spearman.value,
                        "detrended_value": detrended.value,
                        **significance,
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
            event_count = max(1, ceil(len(ordered) * 0.1))
            threshold = (
                ordered[-event_count]
                if direction == "high"
                else ordered[event_count - 1]
            )
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
                        "event_count": sum(
                            1 for is_event in year_events.values() if is_event
                        ),
                        **correlation_significance(result.value, result.sample_count),
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
