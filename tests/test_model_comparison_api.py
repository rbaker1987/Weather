"""Tests for model comparison API."""

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.urls import reverse

from weather.models import Location


@pytest.mark.django_db
class TestModelComparisonAPI:
    """Test the model comparison API endpoint."""

    def test_model_comparison_success(self, client):
        """Test successful model comparison request."""
        latitude = 32.4910
        longitude = -95.3954
        models = ["GFS", "ICON"]

        with patch("requests.get") as mock_get:
            # Mock successful Open-Meteo API response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "hourly": {
                    "time": [
                        (datetime.now() + timedelta(hours=i)).isoformat()
                        for i in range(24)
                    ],
                    "temperature_2m": [70 + i * 0.5 for i in range(24)],
                    "precipitation": [0.0] * 24,
                }
            }
            mock_get.return_value = mock_response

            response = client.get(
                reverse("weather:model-comparison"),
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "models": ",".join(models),
                    "forecast_days": 7,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert len(data["models"]) == 2
        assert data["models"][0]["name"] in models

    def test_model_comparison_missing_params(self, client):
        """Test model comparison with missing required parameters."""
        response = client.get(
            reverse("weather:model-comparison"),
            {"latitude": 32.4910},  # Missing longitude and models
        )

        assert response.status_code == 400
        data = response.json()
        assert data["status"] == "error"

    def test_model_comparison_invalid_coordinates(self, client):
        """Test model comparison with invalid coordinates."""
        response = client.get(
            reverse("weather:model-comparison"),
            {
                "latitude": 999,  # Invalid
                "longitude": -95.3954,
                "models": "GFS",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert data["status"] == "error"

    def test_model_comparison_defaults_forecast_days(self, client):
        """Test that forecast_days defaults to 7 if not provided."""
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "hourly": {
                    "time": [
                        (datetime.now() + timedelta(hours=i)).isoformat()
                        for i in range(168)
                    ],  # 7 days
                    "temperature_2m": [70] * 168,
                    "precipitation": [0.0] * 168,
                }
            }
            mock_get.return_value = mock_response

            response = client.get(
                reverse("weather:model-comparison"),
                {"latitude": 32.4910, "longitude": -95.3954, "models": "GFS"},
            )

        assert response.status_code == 200
        # Verify the API was called with forecast_days=7 in the URL
        mock_get.assert_called()
        call_args = mock_get.call_args[0][0]
        assert "forecast_days=7" in call_args

    def test_model_comparison_api_error_handling(self, client):
        """Test model comparison handles API errors gracefully."""
        with patch("requests.get") as mock_get:
            # Simulate API error
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.json.side_effect = Exception("API Error")
            mock_get.return_value = mock_response

            response = client.get(
                reverse("weather:model-comparison"),
                {"latitude": 32.4910, "longitude": -95.3954, "models": "GFS"},
            )

        assert response.status_code == 500
        data = response.json()
        assert data["status"] == "error"

    def test_model_comparison_multiple_models(self, client):
        """Test comparing multiple weather models."""
        models = ["GFS", "ICON", "ECMWF", "GEM"]

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "hourly": {
                    "time": [
                        (datetime.now() + timedelta(hours=i)).isoformat()
                        for i in range(24)
                    ],
                    "temperature_2m": [70] * 24,
                    "precipitation": [0.0] * 24,
                }
            }
            mock_get.return_value = mock_response

            response = client.get(
                reverse("weather:model-comparison"),
                {
                    "latitude": 32.4910,
                    "longitude": -95.3954,
                    "models": ",".join(models),
                    "forecast_days": 5,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data["models"]) == 4
        # Verify each model was requested
        assert mock_get.call_count == 4


@pytest.mark.django_db
class TestModelDetailView:
    """Test the model detail view."""

    def test_model_detail_view_renders(self, client):
        """Test model detail page renders successfully."""
        response = client.get(
            reverse("weather:model-detail", kwargs={"model_name": "GFS"}),
            {"latitude": 32.4910, "longitude": -95.3954, "forecast_days": 7},
        )

        assert response.status_code == 200
        assert "model_name" in response.context
        assert response.context["model_name"] == "GFS"

    def test_model_detail_view_invalid_model(self, client):
        """Test model detail with invalid model name."""
        response = client.get(
            reverse("weather:model-detail", kwargs={"model_name": "INVALID"}),
            {"latitude": 32.4910, "longitude": -95.3954},
        )

        # Should still render but show error or redirect
        assert response.status_code in [200, 404]

    def test_model_detail_view_forecast_days_clamping(self, client):
        """Test that forecast days are clamped to model max."""
        response = client.get(
            reverse("weather:model-detail", kwargs={"model_name": "HRRR"}),
            {
                "latitude": 32.4910,
                "longitude": -95.3954,
                "forecast_days": 10,  # HRRR max is 2
            },
        )

        assert response.status_code == 200
        # Context should have clamped forecast_days
        assert response.context["forecast_days"] <= 2


@pytest.mark.django_db
class TestModelsView:
    """Test the models comparison page view."""

    def test_models_view_renders(self, client):
        """Test models comparison page renders."""
        response = client.get(reverse("weather:models"))
        assert response.status_code == 200

    def test_models_view_with_location(self, client):
        """Test models view with location selection."""
        location = Location.objects.create(
            name="Test City", latitude=Decimal("32.4910"), longitude=Decimal("-95.3954")
        )
        session = client.session
        session["location_ids"] = [str(location.id)]
        session.save()

        response = client.get(reverse("weather:models"))
        assert response.status_code == 200
        assert "locations" in response.context


@pytest.mark.django_db
class TestTempLocationView:
    """Test temporary location view."""

    def test_temp_location_success(self, client):
        """Test temporary location view with valid coordinates."""
        with patch("requests.get") as mock_get:
            # Mock NWS API responses
            mock_grid = Mock()
            mock_grid.status_code = 200
            mock_grid.json.return_value = {
                "properties": {
                    "gridId": "FWD",
                    "gridX": 100,
                    "gridY": 50,
                    "forecast": "https://api.weather.gov/gridpoints/FWD/100,50/forecast",
                    "observationStations": "https://api.weather.gov/gridpoints/FWD/100,50/stations",
                }
            }

            mock_stations = Mock()
            mock_stations.status_code = 200
            mock_stations.json.return_value = {
                "features": [{"properties": {"stationIdentifier": "KDFW"}}]
            }

            mock_obs = Mock()
            mock_obs.status_code = 200
            mock_obs.json.return_value = {
                "properties": {
                    "temperature": {"value": 21},
                    "relativeHumidity": {"value": 60},
                    "windSpeed": {"value": 10},
                    "windDirection": {"value": 180},
                    "textDescription": "Sunny",
                }
            }

            mock_forecast = Mock()
            mock_forecast.status_code = 200
            mock_forecast.json.return_value = {
                "properties": {
                    "periods": [
                        {
                            "number": 1,
                            "name": "Today",
                            "temperature": 75,
                            "temperatureUnit": "F",
                            "windSpeed": "10 mph",
                            "windDirection": "S",
                            "shortForecast": "Sunny",
                            "detailedForecast": "Sunny skies",
                            "isDaytime": True,
                        }
                    ]
                }
            }

            mock_alerts = Mock()
            mock_alerts.status_code = 200
            mock_alerts.json.return_value = {"features": []}

            mock_get.side_effect = [
                mock_grid,
                mock_stations,
                mock_obs,
                mock_forecast,
                mock_alerts,
            ]

            response = client.get(
                reverse("weather:temp-location"),
                {"latitude": 32.4910, "longitude": -95.3954},
            )

        assert response.status_code == 200
        assert "location" in response.context
        assert response.context["is_temp_location"] is True

    def test_temp_location_missing_coordinates(self, client):
        """Test temporary location view with missing coordinates."""
        response = client.get(reverse("weather:temp-location"))
        # View renders with empty location data
        assert response.status_code == 200

    def test_temp_location_invalid_coordinates(self, client):
        """Test temporary location view with invalid coordinates."""
        response = client.get(
            reverse("weather:temp-location"), {"latitude": 999, "longitude": -95.3954}
        )
        # View renders but shows error message
        assert response.status_code == 200
