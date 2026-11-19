"""Tests for major remaining view branches."""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.urls import reverse


@pytest.mark.django_db
class TestModelDetailBranches:
    def test_model_detail_uses_cached_model_data(self, client):
        cache_key = "model_detail:v4:GFS:det:30.0:-97.0:days:7"
        cache.set(
            cache_key,
            {
                "timezone": "UTC",
                "model_source": "cached",
                "cycle": "12Z",
                "hourly": {"time": ["2026-08-25T12:00:00"]},
            },
        )

        response = client.get(
            reverse("weather:model-detail", kwargs={"model_name": "GFS"}),
            {
                "latitude": "30.0",
                "longitude": "-97.0",
                "forecast_days": "7",
            },
        )

        assert response.status_code == 200
        assert response.context["data"]["model_source"] == "cached"
        assert response.context["model_source"] == "cached"
        assert response.context["cycle"] == "12Z"

    def test_model_detail_reports_missing_coordinates_without_fallback(self, client):
        response = client.get(
            reverse("weather:model-detail", kwargs={"model_name": "GFS"})
        )

        assert response.status_code == 200
        assert "Choose a place on the map" in response.context["error"]
        assert response.context["data"] is None
        assert response.context["locations"] == []
        assert response.context["locations_json"] == "[]"

    def test_model_detail_handles_open_meteo_failure(self, client):
        with patch("requests.get", side_effect=RuntimeError("service down")):
            response = client.get(
                reverse("weather:model-detail", kwargs={"model_name": "ICON"}),
                {"latitude": "30", "longitude": "-97"},
            )

        assert response.status_code == 200
        assert response.context["data"] is None
        assert response.context["model_name"] == "ICON"


@pytest.mark.django_db
class TestTempLocationShell:
    def test_temp_location_renders_without_calling_upstreams(self, client):
        with patch("requests.get", side_effect=AssertionError("no upstream")):
            response = client.get(
                reverse("weather:temp-location"),
                {"latitude": "30", "longitude": "-97"},
            )

        assert response.status_code == 200
        assert response.context["is_temp_location"] is True
        assert "/panel/forecast/" in response.content.decode()
