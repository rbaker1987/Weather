"""Tests for user-related view branches."""

from unittest.mock import Mock, patch

import pytest
from django.test import RequestFactory

from weather.models import DailyForecast, Location
from weather.views import (
    ModelsView,
    _refresh_forecasts_for_location,
)


@pytest.mark.django_db
def test_models_view_does_not_offer_stored_locations():
    Location.objects.create(name="Current", is_current_location=True)
    request = RequestFactory().get("/models")
    view = ModelsView()
    view.request = request
    view.args = ()
    view.kwargs = {}

    context = view.get_context_data()

    assert context["page_title"] == "Weather Models"
    assert "locations" not in context
    assert "default_location_id" not in context


@pytest.mark.django_db
def test_refresh_forecasts_stores_nws_periods():
    location = Location.objects.create(name="Refresh", latitude=30, longitude=-97)
    grid_response = Mock()
    grid_response.json.return_value = {
        "properties": {
            "gridId": "FWD",
            "gridX": 1,
            "gridY": 2,
            "forecast": "https://example.test/forecast",
        }
    }
    forecast_response = Mock()
    forecast_response.json.return_value = {
        "properties": {
            "periods": [
                {
                    "startTime": "2026-08-24T06:00:00Z",
                    "endTime": "2026-08-24T18:00:00Z",
                    "isDaytime": True,
                    "temperature": 78,
                    "windSpeed": "10 to 20 mph",
                    "shortForecast": "Sunny",
                    "detailedForecast": "Clear skies",
                    "probabilityOfPrecipitation": {"value": 10},
                }
            ]
        }
    }
    with patch("requests.get", side_effect=[grid_response, forecast_response]):
        assert _refresh_forecasts_for_location(location) is True

    location.refresh_from_db()
    forecast = DailyForecast.objects.get(location=location)
    assert forecast.temperature == 78
    assert forecast.wind_speed == 15
    assert location.nws_office == "FWD"
