"""Tests for model-comparison API error and classification branches."""

from unittest.mock import Mock, patch

import pytest
import requests

from weather.api.model_comparison_api import ModelComparisonAPIView


@pytest.fixture
def view():
    return ModelComparisonAPIView()


def test_fetch_model_data_rejects_unknown_model(view):
    result = view.fetch_model_data("UNKNOWN", 30, -97, 7)

    assert result == {
        "name": "UNKNOWN",
        "data": None,
        "error": "Unknown model",
    }


def test_fetch_model_data_returns_api_error_payload(view):
    response = Mock()
    response.json.return_value = {"error": True, "reason": "Bad request"}
    response.raise_for_status.return_value = None

    with patch("weather.api.model_comparison_api.requests.get", return_value=response):
        result = view.fetch_model_data("GFS", 30, -97, 20)

    assert result["error"] == "Bad request"
    assert result["data"] is None


def test_fetch_model_data_handles_api_error_without_reason(view):
    response = Mock()
    response.json.return_value = {"error": True}
    response.raise_for_status.return_value = None

    with patch("weather.api.model_comparison_api.requests.get", return_value=response):
        result = view.fetch_model_data("GFS", 30, -97, 7)

    assert result["error"] is None


def test_fetch_model_data_handles_unexpected_error(view):
    with patch(
        "weather.api.model_comparison_api.requests.get",
        side_effect=RuntimeError("unexpected"),
    ):
        result = view.fetch_model_data("GFS", 30, -97, 7)

    assert result["error"] == "unexpected"
    assert result["skipped"] is None


def test_fetch_model_data_handles_timeout(view):
    with patch(
        "weather.api.model_comparison_api.requests.get",
        side_effect=requests.Timeout("slow"),
    ):
        result = view.fetch_model_data("GFS", 30, -97, 7)

    assert result["error"] == "Timeout"
    assert result["skipped"] is None


def test_fetch_model_data_handles_http_error(view):
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError(
        response=Mock(status_code=503)
    )

    with patch("weather.api.model_comparison_api.requests.get", return_value=response):
        result = view.fetch_model_data("GFS", 30, -97, 7)

    assert result["error"] == "HTTP 503"


def test_fetch_all_models_preserves_requested_order(view):
    with patch.object(
        view,
        "fetch_model_data",
        side_effect=lambda model, _lat, _lon, _days: {"name": model},
    ):
        result = view.fetch_all_models(["GFS", "ICON", "NAM"], 30, -97, 7)

    assert [item["name"] for item in result] == ["GFS", "ICON", "NAM"]


@pytest.mark.parametrize(
    ("temperature", "expected_type", "expected_slr"),
    [(20, "snow", 15.0), (30, "sleet", 2.0), (35, "freezing_rain", 0.3), (40, "rain", 1.0)],
)
def test_get_classifies_precipitation_by_surface_temperature(
    view, temperature, expected_type, expected_slr
):
    data = {
        "hourly": {
            "temperature_2m": [temperature],
            "precipitation": [1.0],
        }
    }
    with patch.object(
        view,
        "fetch_all_models",
        return_value=[{"name": "GFS", "data": data, "error": None}],
    ):
        response = view.get(
            Mock(
                query_params={
                    "latitude": "30",
                    "longitude": "-97",
                    "models": "GFS",
                    "forecast_days": "7",
                }
            )
        )

    assert response.data["models"][0]["data"]["hourly"]["precip_type"] == [
        expected_type
    ]
    assert response.data["models"][0]["data"]["hourly"]["snow_liquid_ratio"] == [
        expected_slr
    ]


def test_get_rejects_missing_models_and_invalid_forecast_days(view):
    missing_models = Mock(
        query_params={"latitude": "30", "longitude": "-97", "models": ""}
    )
    invalid_days = Mock(
        query_params={
            "latitude": "30",
            "longitude": "-97",
            "models": "GFS",
            "forecast_days": "bad",
        }
    )

    assert view.get(missing_models).status_code == 400
    assert view.get(invalid_days).status_code == 400


@pytest.mark.parametrize("forecast_days", ["0", "17"])
def test_get_rejects_forecast_days_outside_allowed_range(view, forecast_days):
    request = Mock(
        query_params={
            "latitude": "30",
            "longitude": "-97",
            "models": "GFS",
            "forecast_days": forecast_days,
        }
    )

    response = view.get(request)

    assert response.status_code == 400


def test_get_skips_model_without_data(view):
    with patch.object(
        view,
        "fetch_all_models",
        return_value=[{"name": "GFS", "data": None, "error": "unavailable"}],
    ):
        response = view.get(
            Mock(
                query_params={
                    "latitude": "30",
                    "longitude": "-97",
                    "models": "GFS",
                }
            )
        )

    assert response.status_code == 200
    assert response.data["models"][0]["data"] is None
