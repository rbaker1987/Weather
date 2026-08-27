"""Async integration tests for the SQLAlchemy forecast repository."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from weather.core.models import (
    HourlyForecast,
    Location,
    Temperature,
    WeatherCondition,
    WindCondition,
)
from weather.database import DatabaseManager, ForecastRepository


@pytest_asyncio.fixture
async def repository(tmp_path):
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'weather.db'}")
    await manager.create_tables()
    yield ForecastRepository(manager)
    await manager.drop_tables()
    await manager.engine.dispose()


def make_forecast(location, forecast_time, temperature=70):
    return HourlyForecast(
        location=location,
        forecast_time=forecast_time,
        temperature=Temperature(value=temperature),
        wind=WindCondition(speed=8, direction="SW", gust=15),
        weather=WeatherCondition(
            short_forecast="Partly cloudy",
            detailed_forecast="Clouds increase through the afternoon.",
            icon_url="https://example.test/icon.png",
        ),
    )


@pytest.mark.asyncio
async def test_save_location_creates_then_updates_existing(repository):
    original = Location(name="Austin", latitude=30.2, longitude=-97.7, zip_code="78701")
    saved = await repository.save_location(original)

    updated = await repository.save_location(
        Location(name="Austin", latitude=31.0, longitude=-98.0, zip_code="78702")
    )

    assert saved.id == updated.id
    assert updated.latitude == 31.0
    assert updated.zip_code == "78702"


@pytest.mark.asyncio
async def test_save_forecasts_creates_location_and_preserves_forecast_fields(repository):
    location = Location(name="Dallas", latitude=32.8, longitude=-96.8)
    forecast_time = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)

    saved = await repository.save_forecasts(
        [make_forecast(location, forecast_time, temperature=88)]
    )

    assert len(saved) == 1
    assert saved[0].temperature == 88
    assert saved[0].wind_direction == "SW"
    assert saved[0].location_id is not None


@pytest.mark.asyncio
async def test_save_forecasts_empty_list_returns_empty(repository):
    assert await repository.save_forecasts([]) == []


@pytest.mark.asyncio
async def test_get_forecasts_filters_dates_and_eager_loads_relationships(repository):
    location = Location(name="Houston", latitude=29.7, longitude=-95.4)
    start = datetime(2026, 8, 22, 0, tzinfo=timezone.utc)
    await repository.save_forecasts(
        [
            make_forecast(location, start - timedelta(days=1), temperature=80),
            make_forecast(location, start + timedelta(hours=2), temperature=90),
            make_forecast(location, start + timedelta(days=2), temperature=95),
        ]
    )

    forecasts = await repository.get_forecasts_for_location(
        "Houston", start_date=start.date(), end_date=(start + timedelta(days=1)).date()
    )

    assert [forecast.temperature for forecast in forecasts] == [90]
    assert forecasts[0].location.name == "Houston"
    assert forecasts[0].alerts == []


@pytest.mark.asyncio
async def test_cleanup_old_forecasts_removes_expired_rows(repository):
    location = Location(name="El Paso", latitude=31.8, longitude=-106.5)
    await repository.save_forecasts(
        [make_forecast(location, datetime(2026, 8, 22, tzinfo=timezone.utc))]
    )

    removed = await repository.cleanup_old_forecasts(
        datetime.utcnow().replace(hour=23, minute=59, second=59) + timedelta(days=1)
    )

    assert removed == 1
    assert await repository.get_forecasts_for_location("El Paso") == []


@pytest.mark.asyncio
async def test_get_locations_returns_names_in_order(repository):
    await repository.save_location(Location(name="Zulu"))
    await repository.save_location(Location(name="Alpha"))

    locations = await repository.get_locations()

    assert [location.name for location in locations] == ["Alpha", "Zulu"]
