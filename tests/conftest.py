"""Test fixtures and configuration for pytest."""

import pytest
import asyncio
from datetime import datetime, date
from typing import AsyncGenerator

from weather_app.core.models import Location, Temperature, WindCondition, WeatherCondition, HourlyForecast
from weather_app.data.database import DatabaseManager


@pytest.fixture
def sample_location() -> Location:
    """Sample location for testing."""
    return Location(
        name="Austin, TX",
        latitude=30.2672,
        longitude=-97.7431
    )


@pytest.fixture
def sample_forecast(sample_location: Location) -> HourlyForecast:
    """Sample forecast for testing."""
    return HourlyForecast(
        location=sample_location,
        forecast_time=datetime(2025, 11, 17, 12, 0),
        temperature=Temperature(value=75),
        wind=WindCondition(speed=10, direction="SW"),
        weather=WeatherCondition(short_forecast="Partly Cloudy")
    )


@pytest.fixture
async def test_db() -> AsyncGenerator[DatabaseManager, None]:
    """Test database with in-memory SQLite."""
    db_manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await db_manager.create_tables()
    yield db_manager
    # Cleanup happens automatically with in-memory database


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()