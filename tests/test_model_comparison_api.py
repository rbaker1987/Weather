"""Tests for model comparison API."""

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from django.core.cache import cache
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
        # Verify the API was called with forecast_days=7 in params
        mock_get.assert_called()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["forecast_days"] == 7

    def test_model_comparison_api_error_handling(self, client):
        """Test model comparison handles API errors gracefully."""
        with patch("requests.get") as mock_get:
            # Simulate API error
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.json.side_effect = Exception("API Error")
            mock_response.raise_for_status.side_effect = Exception("API Error")
            mock_get.return_value = mock_response

            response = client.get(
                reverse("weather:model-comparison"),
                {"latitude": 32.4910, "longitude": -95.3954, "models": "GFS"},
            )

        # API returns 200 with error in response data
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        # Check that model has error
        assert data["models"][0]["error"] is not None

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
        # Context should have clamped forecast_days as string
        assert int(response.context["forecast_days"]) <= 2

    @staticmethod
    def _cache_model_data(model_name, hourly):
        max_days = {"NBM": 11, "ICON": 7, "GEM": 10}[model_name]
        cache.set(
            f"model_detail:v4:{model_name}:det:30.0:-97.0:days:{max_days}",
            {"timezone": "UTC", "hourly": hourly},
        )

    def test_model_detail_nbm_adds_static_slr_defaults(self, client):
        self._cache_model_data("NBM", {"time": ["2026-08-25T12:00:00"]})

        response = client.get(
            reverse("weather:model-detail", kwargs={"model_name": "NBM"}),
            {"latitude": "30.0", "longitude": "-97.0"},
        )

        hourly = response.context["data"]["hourly"]
        assert response.status_code == 200
        assert hourly["snow_liquid_ratio"] == [1.0]
        assert hourly["default_slrs"]["snow"] == 10.0

    def test_model_detail_uses_native_precipitation_probabilities(self, client):
        self._cache_model_data(
            "ICON",
            {
                "time": ["2026-08-25T12:00:00"],
                "temperature_2m": [20],
                "snowfall_probability": [80],
                "rain_probability": [10],
            },
        )

        response = client.get(
            reverse("weather:model-detail", kwargs={"model_name": "ICON"}),
            {"latitude": "30.0", "longitude": "-97.0"},
        )

        assert response.context["data"]["hourly"]["precip_type"] == ["snow"]
        assert response.context["data"]["hourly"]["snow_liquid_ratio"] == [10.0]

    def test_model_detail_uses_surface_temperature_fallback(self, client):
        self._cache_model_data(
            "GEM",
            {
                "time": ["2026-08-25T12:00:00", "2026-08-25T13:00:00"],
                "temperature_2m": [10, 50],
            },
        )

        response = client.get(
            reverse("weather:model-detail", kwargs={"model_name": "GEM"}),
            {"latitude": "30.0", "longitude": "-97.0"},
        )

        hourly = response.context["data"]["hourly"]
        assert hourly["precip_type"] == ["snow", "rain"]
        assert hourly["snow_liquid_ratio"] == [12.0, 1.0]

    def test_model_detail_uses_session_location_and_normalizes_parameters(self, client):
        location = Location.objects.create(
            name="Fallback", latitude=30, longitude=-97, is_active=True
        )
        session = client.session
        session["location_ids"] = [str(location.id)]
        session.save()
        cache.set(
            "model_detail:v4:ICON:det:30.0:-97.0:days:7",
            {
                "timezone": "UTC",
                "model_source": "cached",
                "hourly": {"time": ["2026-08-25T12:00:00"]},
            },
        )

        response = client.get(
            reverse("weather:model-detail", kwargs={"model_name": "ICON"}),
            {"forecast_days": "bad", "ens": "unsupported"},
        )

        assert response.status_code == 200
        assert response.context["latitude"] == location.latitude
        assert response.context["longitude"] == location.longitude
        assert response.context["forecast_days"] == "7"
        assert response.context["ensemble"] == "det"
        assert response.context["run_time"].tzinfo is not None

    def test_model_detail_trims_cached_hourly_window(self, client):
        times = [
            "2026-08-25T00:00:00+00:00",
            "2026-08-25T12:00:00+00:00",
            "2026-08-26T12:00:00+00:00",
        ]
        cache.set(
            "model_detail:v4:GEM:det:30.0:-97.0:days:1",
            {
                "timezone": "UTC",
                "hourly": {"time": times, "temperature_2m": [40, 41, 42]},
            },
        )

        response = client.get(
            reverse("weather:model-detail", kwargs={"model_name": "GEM"}),
            {
                "latitude": "30.0",
                "longitude": "-97.0",
                "forecast_days": "1",
            },
        )

        hourly = response.context["data"]["hourly"]
        assert response.status_code == 200
        assert hourly["time"] == times[:2]
        assert hourly["temperature_2m"] == [40, 41]

    def test_aggregate_precip_by_6hour_handles_empty_and_invalid_inputs(self):
        from weather.views import ModelDetailView

        assert ModelDetailView.aggregate_precip_by_6hour({}, []) == {}
        result = ModelDetailView.aggregate_precip_by_6hour(
            {
                "precipitation": [1.0],
                "precip_type": ["snow"],
                "time": ["not-a-time"],
            },
            ["not-a-time", "2026-08-25T12:00:00+00:00"],
        )

        assert result == {"2026-08-25T12:00:00+00:00": {
            "snow": 0.0,
            "sleet": 0.0,
            "freezing_rain": 0.0,
            "rain": 0.0,
            "total": 0.0,
        }}

    def test_aggregate_precip_by_6hour_uses_types_and_default_slrs(self):
        from weather.views import ModelDetailView

        result = ModelDetailView.aggregate_precip_by_6hour(
            {
                "precipitation": [1.0, 2.0, 3.0, 4.0, 5.0],
                "precip_type": ["snow", "sleet", "freezing_rain", "rain", "unknown"],
                "snow_liquid_ratio": [0, 0, 0, 0, 0],
                "time": [
                    "2026-08-25T07:00:00+00:00",
                    "2026-08-25T08:00:00+00:00",
                    "2026-08-25T09:00:00+00:00",
                    "2026-08-25T10:00:00+00:00",
                    "2026-08-25T11:00:00+00:00",
                ],
            },
            ["2026-08-25T12:00:00+00:00"],
        )

        assert result["2026-08-25T12:00:00+00:00"] == {
            "snow": 10.0,
            "sleet": 5.0,
            "freezing_rain": 1.05,
            "rain": 9.0,
            "total": 25.05,
        }

    def test_model_detail_fetches_non_gfs_data_and_classifies_precip(self, client):
        cache.clear()

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {
                "timezone": "UTC",
                "hourly": {
                    "time": [
                        "2026-08-25T00:00:00Z",
                        "2026-08-25T01:00:00Z",
                    ],
                    "temperature_2m": [32, 28],
                    "temperature_850hPa": [20, 18],
                    "temperature_700hPa": [8, 6],
                    "precipitation": [0.3, 0.4],
                },
            }
            mock_get.return_value = mock_response

            response = client.get(
                reverse("weather:model-detail", kwargs={"model_name": "ICON"}),
                {"latitude": "30.0", "longitude": "-97.0", "forecast_days": "2"},
            )

        assert response.status_code == 200
        hourly = response.context["data"]["hourly"]
        assert hourly["precip_type"] == ["snow", "snow"]
        assert all(slr >= 6.0 for slr in hourly["snow_liquid_ratio"])
        assert response.context["forecast_days"] == "2"

    def test_model_detail_uses_native_probabilities_when_levels_missing(self, client):
        cache.clear()

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {
                "timezone": "UTC",
                "hourly": {
                    "time": [
                        "2026-08-25T00:00:00Z",
                        "2026-08-25T01:00:00Z",
                        "2026-08-25T02:00:00Z",
                        "2026-08-25T03:00:00Z",
                        "2026-08-25T04:00:00Z",
                        "2026-08-25T05:00:00Z",
                    ],
                    "temperature_2m": [28, 45, 33, 34, 36, 38],
                    "rain_probability": [0, 0, 80, 10, 0, 0],
                    "snowfall_probability": [0, 0, 10, 80, 0, 0],
                    "freezing_rain_probability": [0, 0, 5, 0, 80, 0],
                    "ice_pellets_probability": [0, 0, 0, 0, 5, 80],
                },
            }
            mock_get.return_value = mock_response

            response = client.get(
                reverse("weather:model-detail", kwargs={"model_name": "ICON"}),
                {"latitude": "30.0", "longitude": "-97.0", "forecast_days": "2"},
            )

        assert response.status_code == 200
        hourly = response.context["data"]["hourly"]
        assert hourly["precip_type"] == [
            "snow",
            "rain",
            "rain",
            "snow",
            "freezing_rain",
            "sleet",
        ]
        assert hourly["snow_liquid_ratio"] == [10.0, 1.0, 1.0, 10.0, 0.5, 2.5]

    def test_model_detail_uses_surface_temperature_fallback_without_levels(self, client):
        cache.clear()

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {
                "timezone": "UTC",
                "hourly": {
                    "time": [
                        "2026-08-25T00:00:00Z",
                        "2026-08-25T01:00:00Z",
                        "2026-08-25T02:00:00Z",
                    ],
                    "temperature_2m": [10, 20, 40],
                    "precipitation": [0.3, 0.4, 0.1],
                },
            }
            mock_get.return_value = mock_response

            response = client.get(
                reverse("weather:model-detail", kwargs={"model_name": "ICON"}),
                {"latitude": "30.0", "longitude": "-97.0", "forecast_days": "2"},
            )

        assert response.status_code == 200
        hourly = response.context["data"]["hourly"]
        assert hourly["precip_type"] == ["snow", "snow", "rain"]
        assert hourly["snow_liquid_ratio"] == [12.0, 10.0, 1.0]


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
