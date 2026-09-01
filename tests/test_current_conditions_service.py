"""Tests for current-conditions caching and NWS integration."""

from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from weather.models import CurrentConditions, Location
from weather.services import CurrentConditionsService


def api_response(payload):
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@pytest.mark.django_db
class TestCurrentConditionsService:
    def test_bearing_to_direction_handles_cardinals_and_missing_values(self):
        assert CurrentConditionsService._bearing_to_direction(None) == ""
        assert CurrentConditionsService._bearing_to_direction(0) == "N"
        assert CurrentConditionsService._bearing_to_direction(90) == "E"
        assert CurrentConditionsService._bearing_to_direction(180) == "S"
        assert CurrentConditionsService._bearing_to_direction(270) == "W"
        assert CurrentConditionsService._bearing_to_direction(360) == "N"

    def test_fetch_skips_location_without_coordinates(self):
        location = Location.objects.create(name="Unknown")

        with patch("weather.services.logger.warning") as warning:
            result = CurrentConditionsService.fetch_and_cache_current_conditions(location)

        assert result is None
        warning.assert_called_once()

    def test_get_or_fetch_returns_fresh_cached_conditions(self):
        location = Location.objects.create(name="Cached")
        current = CurrentConditions.objects.create(
            location=location,
            temperature=72,
            condition="Sunny",
            wind_speed=5,
            humidity=50,
            last_observation_time=timezone.now(),
        )

        with patch.object(
            CurrentConditionsService, "fetch_and_cache_current_conditions"
        ) as fetch:
            result = CurrentConditionsService.get_or_fetch_current_conditions(location)

        assert result.pk == current.pk
        fetch.assert_not_called()

    def test_get_or_fetch_fetches_when_cache_missing(self):
        location = Location.objects.create(name="Missing")
        replacement = object()

        with patch.object(
            CurrentConditionsService,
            "fetch_and_cache_current_conditions",
            return_value=replacement,
        ) as fetch:
            result = CurrentConditionsService.get_or_fetch_current_conditions(location)

        assert result is replacement
        fetch.assert_called_once_with(location)

    def test_fetch_and_cache_converts_observation_values(self):
        location = Location.objects.create(name="Austin", latitude=30, longitude=-97)
        points = api_response(
            {"properties": {"observationStations": "https://example.test/stations"}}
        )
        stations = api_response(
            {"features": [{"properties": {"stationIdentifier": "KAUS"}}]}
        )
        observation = api_response(
            {
                "properties": {
                    "temperature": {"value": 20},
                    "apparentTemperature": {"value": 18},
                    "textDescription": "Clear",
                    "windSpeed": {"value": 4},
                    "windDirection": {"value": 180},
                    "windGust": {"value": 8},
                    "relativeHumidity": {"value": 55},
                    "precipitationLast3Hours": {"value": 2.54},
                    "barometricPressure": {"value": 101325},
                    "visibility": {"value": 1609.34},
                }
            }
        )

        with patch(
            "requests.get", side_effect=[points, stations, observation]
        ):
            result = CurrentConditionsService.fetch_and_cache_current_conditions(location)

        assert result.temperature == 68
        assert result.feels_like_temperature == 64
        assert result.wind_direction == "S"
        assert result.wind_speed == 8
        assert result.wind_gust == 17
        assert result.humidity == 55
        assert result.precipitation == pytest.approx(0.1)
        assert result.pressure == pytest.approx(1013.25)
        assert result.visibility == pytest.approx(1)

    def test_fetch_and_cache_returns_none_for_request_failure(self):
        import requests

        location = Location.objects.create(name="Offline", latitude=30, longitude=-97)
        with patch(
            "requests.get",
            side_effect=requests.RequestException("offline"),
        ):
            result = CurrentConditionsService.fetch_and_cache_current_conditions(location)

        assert result is None
