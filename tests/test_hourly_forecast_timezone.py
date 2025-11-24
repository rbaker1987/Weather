import json
from unittest.mock import MagicMock, patch

from django.test import Client

# Coordinates for a location expected to resolve to America/Chicago
LAT = 32.5107
LON = -95.4094

MOCK_GRID_JSON = {"properties": {"forecastHourly": "https://example.com/hourly"}}

MOCK_HOURLY_JSON = {
    "properties": {
        "periods": [
            {
                "startTime": "2025-11-20T17:00:00Z",
                "temperature": 77,
                "temperatureUnit": "F",
                "shortForecast": "Mostly Cloudy",
                "windSpeed": "5 mph",
                "windDirection": "E",
                "probabilityOfPrecipitation": {"value": 10},
            }
        ]
    }
}


class DummyResp:
    def __init__(self, json_data):
        self._json = json_data
        self.status_code = 200
        self.ok = True

    def json(self):
        return self._json

    def raise_for_status(self):
        return None


@patch("weather.api.hourly_forecast_api.requests.get")
@patch("weather.api.hourly_forecast_api.TimezoneFinder")
def test_hourly_forecast_includes_timezone(mock_tzfinder, mock_get):
    # Mock timezone finder
    instance = MagicMock()
    instance.timezone_at.return_value = "America/Chicago"
    mock_tzfinder.return_value = instance

    # Mock sequential requests: first points, then hourly forecast
    mock_get.side_effect = [DummyResp(MOCK_GRID_JSON), DummyResp(MOCK_HOURLY_JSON)]

    client = Client()
    resp = client.get(f"/api/hourly_forecast/?lat={LAT}&lon={LON}&hours=1")
    assert resp.status_code == 200, resp.content
    data = json.loads(resp.content)
    assert data.get("timezone") == "America/Chicago"
    assert "hours" in data
    assert data["hours"][0]["condition"] == "Mostly Cloudy"
    # Ensure caching works: second call should not invoke timezone_at again
    mock_get.side_effect = [DummyResp(MOCK_GRID_JSON), DummyResp(MOCK_HOURLY_JSON)]
    resp2 = client.get(f"/api/hourly_forecast/?lat={LAT}&lon={LON}&hours=1")
    assert resp2.status_code == 200
    # timezone_at should still have been called only once because cache hit prevents second call
    instance.timezone_at.assert_called_once()
