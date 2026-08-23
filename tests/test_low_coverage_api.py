"""Coverage tests for low-coverage API endpoints."""

from unittest.mock import Mock, patch

import pytest
from rest_framework.test import APIRequestFactory

from weather.api.climate_normals_api import ClimateNormalsAPIView
from weather.api.summarize_api import SummarizeForecastAPIView
from weather.models import Location


@pytest.fixture
def request_factory():
    return APIRequestFactory()


class TestSummarizeForecastAPIView:
    def test_post_requires_text(self, request_factory):
        request = request_factory.post("/summarize", {"text": "   "}, format="json")

        response = SummarizeForecastAPIView.as_view()(request)

        assert response.status_code == 400
        assert response.data["error"] == "text is required"

    def test_post_returns_short_text_unchanged(self, request_factory):
        request = request_factory.post(
            "/summarize", {"text": "Sunny and warm", "max_length": 30}, format="json"
        )

        response = SummarizeForecastAPIView.as_view()(request)

        assert response.status_code == 200
        assert response.data == {"summary": "Sunny and warm"}

    def test_post_extracts_key_weather_sentences(self, request_factory):
        request = request_factory.post(
            "/summarize",
            {
                "text": "Sunny skies today. Rain arrives tomorrow. Winds increase later.",
                "max_length": 60,
            },
            format="json",
        )

        response = SummarizeForecastAPIView.as_view()(request)

        assert response.status_code == 200
        assert "Sunny skies today" in response.data["summary"]

    @pytest.mark.parametrize(
        ("text", "max_length", "expected"),
        [
            ("A quiet day with no notable conditions.", 20, "A quiet day with..."),
            ("First sentence. Second sentence.", 25, "First sentence."),
        ],
    )
    def test_simple_summarize_fallbacks(self, text, max_length, expected):
        summary = SummarizeForecastAPIView()._simple_summarize(text, max_length)

        assert summary == expected

    def test_post_returns_error_when_summarization_raises(self, request_factory):
        request = request_factory.post(
            "/summarize", {"text": "A long forecast", "max_length": 4}, format="json"
        )

        with patch.object(
            SummarizeForecastAPIView,
            "_simple_summarize",
            side_effect=RuntimeError("broken"),
        ):
            response = SummarizeForecastAPIView.as_view()(request)

        assert response.status_code == 500
        assert response.data["error"] == "Summarization failed"


@pytest.mark.django_db
class TestClimateNormalsAPIView:
    def test_get_requires_location_id(self, request_factory):
        response = ClimateNormalsAPIView.as_view()(request_factory.get("/climate"))

        assert response.status_code == 400
        assert response.data["error"] == "location_id parameter is required"

    def test_get_rejects_custom_location(self, request_factory):
        request = request_factory.get("/climate", {"location_id": "custom"})

        response = ClimateNormalsAPIView.as_view()(request)

        assert response.status_code == 400
        assert response.data["status"] == "custom_location"

    def test_get_returns_cached_normals(self, request_factory):
        location = Location.objects.create(
            name="Cached", avg_high_temp=80, avg_low_temp=60
        )
        request = request_factory.get("/climate", {"location_id": str(location.id)})

        response = ClimateNormalsAPIView.as_view()(request)

        assert response.status_code == 200
        assert response.data["status"] == "cached"

    def test_get_fetches_and_saves_normals(self, request_factory):
        location = Location.objects.create(
            name="Fetched", latitude=30, longitude=-97
        )
        request = request_factory.get("/climate", {"location_id": str(location.id)})

        with patch.object(
            ClimateNormalsAPIView,
            "_fetch_climate_normals",
            return_value=(85.5, 64.5),
        ):
            response = ClimateNormalsAPIView.as_view()(request)

        location.refresh_from_db()
        assert response.status_code == 200
        assert response.data["status"] == "success"
        assert location.avg_high_temp == 85.5
        assert location.avg_low_temp == 64.5

    def test_get_returns_error_when_normals_unavailable(self, request_factory):
        location = Location.objects.create(name="Unavailable", latitude=30, longitude=-97)
        request = request_factory.get("/climate", {"location_id": str(location.id)})

        with patch.object(
            ClimateNormalsAPIView,
            "_fetch_climate_normals",
            return_value=(None, None),
        ):
            response = ClimateNormalsAPIView.as_view()(request)

        assert response.status_code == 500
        assert response.data["status"] == "error"

    def test_fetch_climate_normals_calculates_averages(self):
        points = Mock()
        points.json.return_value = {
            "properties": {
                "relativeLocation": {"properties": {"city": "Austin", "state": "TX"}},
                "forecast": "https://example.test/forecast",
            }
        }
        forecast = Mock()
        forecast.json.return_value = {
            "properties": {
                "periods": [
                    {"isDaytime": True, "temperature": 80},
                    {"isDaytime": False, "temperature": 60},
                    {"isDaytime": True, "temperature": 86},
                    {"isDaytime": False, "temperature": 64},
                ]
            }
        }

        with patch(
            "weather.api.climate_normals_api.requests.get",
            side_effect=[points, forecast],
        ):
            result = ClimateNormalsAPIView()._fetch_climate_normals(30, -97)

        assert result == (83.0, 62.0)

    @pytest.mark.parametrize(
        "payload",
        [{}, {"properties": {}}, {"properties": {"forecast": "url"}}],
    )
    def test_fetch_climate_normals_handles_incomplete_points_response(self, payload):
        response = Mock()
        response.json.return_value = payload

        with patch("weather.api.climate_normals_api.requests.get", return_value=response):
            result = ClimateNormalsAPIView()._fetch_climate_normals(30, -97)

        assert result == (None, None)

    def test_fetch_climate_normals_handles_request_error(self):
        import requests

        with patch(
            "weather.api.climate_normals_api.requests.get",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            result = ClimateNormalsAPIView()._fetch_climate_normals(30, -97)

        assert result == (None, None)
