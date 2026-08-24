"""Tests for weather service persistence and orchestration paths."""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from weather.core.models import DailyForecast as PydanticDaily
from weather.core.models import HourlyForecast as PydanticHourly
from weather.core.models import Location as PydanticLocation
from weather.core.models import Temperature, WeatherCondition, WindCondition
from weather.models import DailyForecast, HourlyForecast, Location
from weather.services import WeatherIntegrationService


def make_hourly(location, hour, temperature=70):
    return PydanticHourly(
        location=location,
        forecast_time=datetime(2026, 8, 24, hour, tzinfo=timezone.utc),
        temperature=Temperature(value=temperature),
        wind=WindCondition(speed=8, direction="N", gust=12),
        weather=WeatherCondition(
            short_forecast="Clear", detailed_forecast="Clear skies"
        ),
        precipitation_probability=20,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_pydantic_location_conversion_reuses_active_location():
    existing = await sync_to_async(Location.objects.create)(
        name="Austin", is_active=True
    )
    service = WeatherIntegrationService()

    result = await service.pydantic_to_django_location(
        PydanticLocation(name="Austin", latitude=30, longitude=-97)
    )

    assert result.pk == existing.pk


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_pydantic_location_conversion_creates_with_coordinates():
    service = WeatherIntegrationService()

    result = await service.pydantic_to_django_location(
        PydanticLocation(name="Dallas", latitude=32.8, longitude=-96.8, zip_code="75201")
    )

    assert result.name == "Dallas"
    assert result.latitude == 32.8
    assert result.longitude == -96.8
    assert result.zip_code == "75201"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_save_daily_forecasts_counts_only_new_records():
    location = await sync_to_async(Location.objects.create)(name="Austin")
    hourly = [make_hourly(PydanticLocation(name="Austin"), 12, 75)]
    daily = PydanticDaily(
        date=date(2026, 8, 24),
        location=hourly[0].location,
        hourly_forecasts=hourly,
    )
    service = WeatherIntegrationService()

    first = await service.save_daily_forecasts(location, [daily])
    second = await service.save_daily_forecasts(location, [daily])

    saved = await sync_to_async(DailyForecast.objects.get)(location=location)
    assert first == 1
    assert second == 0
    assert saved.temperature == 75
    assert saved.high_temperature == 75
    assert saved.wind_direction == "N"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_save_hourly_forecasts_persists_fields_and_updates_existing():
    location = await sync_to_async(Location.objects.create)(name="Austin")
    forecast = make_hourly(PydanticLocation(name="Austin"), 13, 80)
    service = WeatherIntegrationService()

    first = await service.save_hourly_forecasts(location, [forecast])
    forecast.temperature = Temperature(value=82)
    second = await service.save_hourly_forecasts(location, [forecast])

    saved = await sync_to_async(HourlyForecast.objects.get)(location=location)
    assert first == 1
    assert second == 0
    assert saved.temperature == 82
    assert saved.wind_gust == 12
    assert saved.precipitation_probability == 20


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_bulk_update_ignores_missing_ids_and_reports_results():
    location = await sync_to_async(Location.objects.create)(name="Austin")
    service = WeatherIntegrationService()
    service.get_location_by_id = AsyncMock(side_effect=[location, None])
    service.update_forecasts_for_location = AsyncMock(
        return_value={"success": True, "daily_forecasts": 1}
    )

    result = await service.bulk_update_forecasts([str(location.id), "missing"])

    assert result["success"] is True
    assert result["total_locations"] == 1
    assert result["results"][0]["location"] == "Austin"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_location_from_input_handles_empty_geocode_result():
    service = WeatherIntegrationService()

    with patch(
        "weather.services.create_location_from_string",
        new=AsyncMock(return_value=None),
    ):
        result = await service.create_location_from_input("Unknown")

    assert result is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_forecasts_reports_missing_data_and_unavailable_service():
    location = await sync_to_async(Location.objects.create)(name="Austin")
    service = WeatherIntegrationService()

    service.weather_service = AsyncMock()
    service.weather_service.get_forecasts_for_locations.return_value = {}
    assert await service.update_forecasts_for_location(location) == {
        "error": "No forecast data received"
    }

    service.weather_service = None
    with patch("weather.services.WEATHER_BACKEND_AVAILABLE", False):
        assert await service.update_forecasts_for_location(location) == {
            "error": "Weather service not available"
        }
