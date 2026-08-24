"""Tests for remaining service cache and orchestration branches."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from django.core.cache import cache
from django.utils import timezone

from weather.core.models import Location as PydanticLocation
from weather.models import CurrentConditions, DailyForecast, Location
from weather.services import (
    AlertsService,
    CurrentConditionsService,
    ForecastService,
    WeatherIntegrationService,
)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_location_from_input_creates_geocoded_location():
    service = WeatherIntegrationService()
    geocoded = PydanticLocation(
        name="Austin", latitude=30.2, longitude=-97.7, zip_code="78701"
    )

    with patch(
        "weather.services.create_location_from_string",
        new=AsyncMock(return_value=geocoded),
    ):
        result = await service.create_location_from_input("Austin")

    assert result.name == "Austin"
    assert result.latitude == 30.2
    assert result.zip_code == "78701"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_location_from_input_handles_geocoder_exception():
    service = WeatherIntegrationService()

    with patch(
        "weather.services.create_location_from_string",
        new=AsyncMock(side_effect=RuntimeError("geocoder down")),
    ):
        result = await service.create_location_from_input("Austin")

    assert result is None


@pytest.mark.django_db
def test_current_conditions_fetches_when_stale_or_forced():
    location = Location.objects.create(name="Austin")
    current = CurrentConditions.objects.create(
        location=location,
        temperature=70,
        condition="Clear",
        wind_speed=5,
        humidity=50,
        last_observation_time=timezone.now(),
    )
    CurrentConditions.objects.filter(pk=current.pk).update(
        updated_at=timezone.now() - timedelta(minutes=20)
    )
    location.refresh_from_db()

    with patch.object(
        CurrentConditionsService,
        "fetch_and_cache_current_conditions",
        return_value="fresh",
    ) as fetch:
        assert (
            CurrentConditionsService.get_or_fetch_current_conditions(location)
            == "fresh"
        )
        assert (
            CurrentConditionsService.get_or_fetch_current_conditions(
                location, force_refresh=True
            )
            == "fresh"
        )

    assert fetch.call_count == 2


@pytest.mark.django_db
def test_forecast_services_refresh_stale_data_and_return_queryset():
    location = Location.objects.create(name="Austin")
    forecast = DailyForecast.objects.create(
        location=location,
        forecast_date=timezone.now().date(),
        period_start=timezone.now(),
        period_end=timezone.now() + timedelta(hours=12),
        temperature=75,
        short_forecast="Sunny",
        wind_speed=5,
        last_api_update=timezone.now() - timedelta(minutes=20),
    )

    with patch(
        "weather.services.SyncWeatherService.update_forecasts_for_location"
    ) as update:
        daily = ForecastService.get_or_fetch_daily_forecasts(location)
        hourly = ForecastService.get_or_fetch_hourly_forecasts(
            location, force_refresh=True
        )

    update.assert_any_call(location)
    assert list(daily) == [forecast]
    assert list(hourly) == []


@pytest.mark.django_db
def test_alert_service_force_refreshes_and_cache_can_be_cleared():
    location = Location.objects.create(name="Austin")
    cache_key = f"alerts:last_fetch:{location.id}"
    cache.set(cache_key, timezone.now(), 900)

    with patch.object(AlertsService, "fetch_and_cache_alerts", return_value=[]) as fetch:
        result = AlertsService.get_or_fetch_alerts(location, force_refresh=True)

    fetch.assert_called_once_with(location)
    assert result == []
    cache.delete(cache_key)
    assert cache.get(cache_key) is None
