"""Additional climate-normals API edge-case tests."""

from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.test import RequestFactory

from weather.api.climate_normals_api import ClimateNormalsAPIView
from weather.models import Location


@pytest.mark.django_db
class TestClimateNormalsEdgeCases:
    def test_get_returns_error_for_missing_location(self):
        request = RequestFactory().get(
            "/climate", {"location_id": str(uuid4())}
        )

        response = ClimateNormalsAPIView.as_view()(request)

        assert response.status_code == 500
        assert response.data["status"] == "error"

    @pytest.mark.parametrize(
        "payload",
        [
            {"properties": {"relativeLocation": {"properties": {}}}},
            {"properties": {"relativeLocation": {"properties": {"city": "Austin"}}}},
            {"properties": {"relativeLocation": {"properties": {"state": "TX"}}}},
            {
                "properties": {
                    "relativeLocation": {
                        "properties": {"city": "Austin", "state": "TX"}
                    }
                }
            },
        ],
    )
    def test_fetch_returns_none_for_incomplete_location_or_forecast(self, payload):
        response = Mock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None

        with patch(
            "weather.api.climate_normals_api.requests.get", return_value=response
        ):
            result = ClimateNormalsAPIView()._fetch_climate_normals(30, -97)

        assert result == (None, None)
