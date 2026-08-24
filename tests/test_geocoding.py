"""Tests for asynchronous geocoding utilities."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from geopy.exc import GeocoderTimedOut

from weather.core.models import Location
from weather.utils.geocoding import (
    AsyncGeocoder,
    GeocodingError,
    bulk_geocode_locations,
    create_location_from_string,
)


@pytest.mark.asyncio
async def test_geocode_with_retry_returns_coordinates():
    geocoder = AsyncGeocoder()
    result = Mock(latitude=30.2, longitude=-97.7)
    geocoder._run_in_executor = AsyncMock(return_value=result)

    assert await geocoder.geocode_with_retry("Austin") == (30.2, -97.7)


@pytest.mark.asyncio
async def test_geocode_with_retry_returns_none_without_result():
    geocoder = AsyncGeocoder()
    geocoder._run_in_executor = AsyncMock(return_value=None)

    assert await geocoder.geocode_with_retry("Unknown") is None


@pytest.mark.asyncio
async def test_geocode_with_retry_retries_then_raises():
    geocoder = AsyncGeocoder()
    geocoder.max_retries = 2
    geocoder._run_in_executor = AsyncMock(
        side_effect=GeocoderTimedOut("timeout")
    )

    with (
        patch("weather.utils.geocoding.asyncio.sleep", new=AsyncMock()) as sleep,
        pytest.raises(GeocodingError, match="Failed to geocode"),
    ):
        await geocoder.geocode_with_retry("Austin")

    assert sleep.await_count == 1
    assert geocoder._run_in_executor.await_count == 2


@pytest.mark.asyncio
async def test_geocode_with_retry_wraps_unexpected_errors():
    geocoder = AsyncGeocoder()
    geocoder._run_in_executor = AsyncMock(side_effect=RuntimeError("broken"))

    with pytest.raises(GeocodingError, match="Unexpected geocoding error"):
        await geocoder.geocode_with_retry("Austin")


@pytest.mark.asyncio
async def test_reverse_geocode_returns_address_or_none():
    geocoder = AsyncGeocoder()
    geocoder._run_in_executor = AsyncMock(return_value=Mock(address="Austin, TX"))
    assert await geocoder.reverse_geocode(30, -97) == "Austin, TX"

    geocoder._run_in_executor = AsyncMock(return_value=None)
    assert await geocoder.reverse_geocode(30, -97) is None


@pytest.mark.asyncio
async def test_reverse_geocode_handles_error():
    geocoder = AsyncGeocoder()
    geocoder._run_in_executor = AsyncMock(side_effect=RuntimeError("offline"))

    assert await geocoder.reverse_geocode(30, -97) is None


@pytest.mark.asyncio
async def test_enrich_location_adds_coordinates_when_available():
    geocoder = AsyncGeocoder()
    geocoder.geocode_with_retry = AsyncMock(return_value=(30.2, -97.7))
    location = Location(name="Austin")

    result = await geocoder.enrich_location(location)

    assert result.latitude == 30.2
    assert result.longitude == -97.7


@pytest.mark.asyncio
async def test_enrich_location_keeps_location_when_geocode_fails():
    geocoder = AsyncGeocoder()
    geocoder.geocode_with_retry = AsyncMock(return_value=None)
    location = Location(name="Unknown")

    result = await geocoder.enrich_location(location)

    assert result == location
    assert result.latitude is None


@pytest.mark.asyncio
async def test_create_location_from_string_parses_coordinates():
    with patch(
        "weather.utils.geocoding.AsyncGeocoder.reverse_geocode",
        new=AsyncMock(return_value="Austin, TX"),
    ):
        location = await create_location_from_string("30.2, -97.7")

    assert location == Location(
        name="Austin, TX", latitude=30.2, longitude=-97.7
    )


@pytest.mark.asyncio
async def test_create_location_from_string_enriches_place_name():
    with patch(
        "weather.utils.geocoding.AsyncGeocoder.enrich_location",
        new=AsyncMock(return_value=Location(name="Austin", latitude=30, longitude=-97)),
    ):
        location = await create_location_from_string("Austin")

    assert location.latitude == 30


@pytest.mark.asyncio
async def test_create_location_from_string_treats_invalid_coordinates_as_place():
    with patch(
        "weather.utils.geocoding.AsyncGeocoder.enrich_location",
        new=AsyncMock(return_value=Location(name="91, -97")),
    ) as enrich:
        location = await create_location_from_string("91, -97")

    enrich.assert_awaited_once()
    assert location.name == "91, -97"


@pytest.mark.asyncio
async def test_bulk_geocode_locations_runs_all_inputs():
    locations = [Location(name="Austin"), Location(name="Dallas")]
    with patch(
        "weather.utils.geocoding.create_location_from_string",
        new=AsyncMock(side_effect=locations),
    ):
        result = await bulk_geocode_locations(["Austin", "Dallas"])

    assert result == locations
