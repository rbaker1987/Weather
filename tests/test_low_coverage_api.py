"""Coverage tests for low-coverage API endpoints."""

from unittest.mock import patch

import pytest
from rest_framework.test import APIRequestFactory

from weather.api.summarize_api import SummarizeForecastAPIView


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
