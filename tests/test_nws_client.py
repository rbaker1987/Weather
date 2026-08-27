"""Tests for the asynchronous NWS client and service."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from weather.api.nws_client import (
    ForecastNotAvailableError,
    LocationNotFoundError,
    NWSAPIError,
    NWSClient,
    RateLimitError,
    WeatherService,
)
from weather.core.models import Location


@pytest.fixture
def nws_client():
    return NWSClient()


def alert(start, end=None):
    return {
        "properties": {
            "event": "Heat Advisory",
            "headline": "Hot",
            "description": "Stay hydrated",
            "onset": start.isoformat(),
            "ends": end.isoformat() if end else None,
            "severity": "Severe",
        }
    }


@pytest.mark.asyncio
async def test_parse_hourly_period_converts_temperature_and_links_alert(nws_client):
    start = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
    parsed_alert = nws_client._parse_alert(alert(start, start + timedelta(hours=2)))

    forecast = nws_client._parse_hourly_period(
        {
            "startTime": start.isoformat().replace("+00:00", "Z"),
            "temperature": 20,
            "temperatureUnit": "C",
            "windSpeed": "10 mph",
            "windDirection": "S",
            "windGust": "15 mph",
            "probabilityOfPrecipitation": {"value": "40"},
            "shortForecast": "Sunny",
            "detailedForecast": "Warm.",
            "icon": "icon.png",
        },
        Location(name="Austin"),
        [parsed_alert],
    )

    assert forecast.temperature.value == 68
    assert forecast.wind.speed == 10
    assert forecast.wind.gust == 15
    assert forecast.precipitation_probability == 40
    assert forecast.alerts == [parsed_alert]


@pytest.mark.asyncio
async def test_parse_hourly_period_handles_invalid_optional_values(nws_client):
    forecast = nws_client._parse_hourly_period(
        {
            "startTime": "2026-08-24T12:00:00Z",
            "temperature": 70,
            "temperatureUnit": "F",
            "windSpeed": "calm",
            "windGust": "unknown",
            "probabilityOfPrecipitation": {"value": "bad"},
        },
        Location(name="Austin"),
        [],
    )

    assert forecast.wind.speed == 0
    assert forecast.wind.gust is None
    assert forecast.precipitation_probability is None
    assert forecast.weather.short_forecast == "Unknown"


@pytest.mark.asyncio
async def test_parse_alert_supports_sent_fallback_and_optional_end(nws_client):
    parsed = nws_client._parse_alert(
        {"properties": {"event": "Watch", "sent": "2026-08-24T12:00:00+00:00"}}
    )

    assert parsed.event == "Watch"
    assert parsed.end_time is None


@pytest.mark.asyncio
async def test_get_forecast_for_location_orchestrates_and_limits_results(nws_client):
    location = Location(name="Austin", latitude=30, longitude=-97)
    period = {
        "startTime": "2026-08-24T12:00:00Z",
        "temperature": 80,
        "temperatureUnit": "F",
        "windSpeed": "5 mph",
        "shortForecast": "Sunny",
    }
    nws_client.get_grid_point = AsyncMock(
        return_value={"properties": {"cwa": "EWX", "gridX": 1, "gridY": 2}}
    )
    nws_client.get_hourly_forecast = AsyncMock(
        return_value={"properties": {"periods": [period]}}
    )
    nws_client.get_alerts_for_point = AsyncMock(return_value=[])

    result = await nws_client.get_forecast_for_location(location)

    assert len(result) == 1
    assert result[0].short_forecast == "Sunny"
    nws_client.get_hourly_forecast.assert_awaited_once_with("EWX", 1, 2)


@pytest.mark.asyncio
async def test_get_forecast_for_location_requires_coordinates(nws_client):
    with pytest.raises(ValueError, match="must have coordinates"):
        await nws_client.get_forecast_for_location(Location(name="Unknown"))


@pytest.mark.asyncio
async def test_get_forecast_for_location_wraps_client_errors(nws_client):
    location = Location(name="Austin", latitude=30, longitude=-97)
    nws_client.get_grid_point = AsyncMock(side_effect=LocationNotFoundError("missing"))

    with pytest.raises(ForecastNotAvailableError, match="Forecast not available"):
        await nws_client.get_forecast_for_location(location)


@pytest.mark.asyncio
async def test_get_alerts_returns_empty_on_client_error(nws_client):
    nws_client._make_request = AsyncMock(side_effect=NWSAPIError("down"))

    assert await nws_client.get_alerts_for_point(30, -97) == []


@pytest.mark.asyncio
async def test_weather_service_groups_and_records_failed_locations():
    service = WeatherService()
    good = Location(name="Good", latitude=30, longitude=-97)
    bad = Location(name="Bad", latitude=31, longitude=-98)
    service.nws_client.get_forecast_for_location = AsyncMock(
        side_effect=[["forecast"], RuntimeError("failed")]
    )

    result = await service.get_forecasts_for_locations([good, bad])

    assert result == {"Good": ["forecast"], "Bad": []}
    assert service.group_hourly_into_daily([]) == []
    await service.close()


@pytest.mark.asyncio
async def test_nws_client_close_closes_existing_client(nws_client):
    client = AsyncMock()
    nws_client._client = client

    await nws_client.close()

    client.aclose.assert_awaited_once_with()
    assert nws_client._client is None


@pytest.mark.asyncio
async def test_make_request_returns_data_and_passes_parameters(nws_client):
    response = Mock()
    response.json.return_value = {"properties": {"ok": True}}
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    nws_client._client = client
    nws_client.rate_limit_delay = 0

    result = await nws_client._make_request("https://example.test", {"page": 1})

    assert result == {"properties": {"ok": True}}
    client.get.assert_awaited_once_with("https://example.test", params={"page": 1})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "exception"),
    [(404, LocationNotFoundError), (429, RateLimitError), (500, NWSAPIError)],
)
async def test_make_request_translates_api_error_statuses(nws_client, status, exception):
    response = Mock()
    response.json.return_value = {"status": status, "title": "Failure"}
    response.raise_for_status.return_value = None
    client = AsyncMock()
    client.get.return_value = response
    nws_client._client = client
    nws_client.rate_limit_delay = 0

    with pytest.raises(exception):
        await nws_client._make_request("https://example.test")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 429, 503])
async def test_make_request_translates_http_status_errors(nws_client, status):
    response = httpx.Response(status, text="failure", request=httpx.Request("GET", "https://example.test"))
    client = AsyncMock()
    client.get.side_effect = httpx.HTTPStatusError("failure", request=response.request, response=response)
    nws_client._client = client
    nws_client.rate_limit_delay = 0

    exception = {
        404: LocationNotFoundError,
        429: RateLimitError,
        503: NWSAPIError,
    }[status]
    with pytest.raises(exception):
        await nws_client._make_request("https://example.test")


@pytest.mark.asyncio
async def test_make_request_translates_request_errors_and_rate_limits(nws_client):
    client = AsyncMock()
    client.get.side_effect = httpx.ConnectError("offline", request=Mock())
    nws_client._client = client
    nws_client.rate_limit_delay = 1
    nws_client._last_request_time = 100

    with patch("weather.api.nws_client.asyncio.get_event_loop") as get_loop, patch(
        "weather.api.nws_client.asyncio.sleep", new=AsyncMock()
    ) as sleep:
        get_loop.return_value.time.side_effect = [100, 100, 101]
        with pytest.raises(NWSAPIError, match="Request failed"):
            await nws_client._make_request("https://example.test")

    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_nws_client_url_wrappers(nws_client):
    nws_client._make_request = AsyncMock(return_value={"ok": True})

    assert await nws_client.get_grid_point(30, -97) == {"ok": True}
    assert await nws_client.get_forecast_grid_data("EWX", 1, 2) == {"ok": True}
    assert await nws_client.get_hourly_forecast("EWX", 1, 2) == {"ok": True}

    assert nws_client._make_request.await_args_list[0].args[0].endswith("/points/30,-97")
    assert nws_client._make_request.await_args_list[1].args[0].endswith("/gridpoints/EWX/1,2")
    assert nws_client._make_request.await_args_list[2].args[0].endswith(
        "/gridpoints/EWX/1,2/forecast/hourly"
    )
