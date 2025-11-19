"""Tests for date/time utilities."""

from datetime import datetime

import pytest

from weather.utils.datetime_utils import (
    create_datetime_from_date_and_time,
    describe_temperature_range,
    format_temperature_trend,
    format_time_12hour,
    normalize_weather_description,
    round_temperature_description,
    parse_time_12hour,
)


class TestTimeFormatting:
    """Test time formatting functions."""

    def test_format_time_12hour(self):
        """Test 12-hour time formatting."""
        # Morning hours
        assert format_time_12hour(datetime(2025, 1, 1, 0)) == "12AM"
        assert format_time_12hour(datetime(2025, 1, 1, 1)) == "01AM"
        assert format_time_12hour(datetime(2025, 1, 1, 9)) == "09AM"
        assert format_time_12hour(datetime(2025, 1, 1, 11)) == "11AM"

        # Noon and afternoon
        assert format_time_12hour(datetime(2025, 1, 1, 12)) == "12PM"
        assert format_time_12hour(datetime(2025, 1, 1, 13)) == "01PM"
        assert format_time_12hour(datetime(2025, 1, 1, 15)) == "03PM"
        assert format_time_12hour(datetime(2025, 1, 1, 21)) == "09PM"

        # Late night
        assert format_time_12hour(datetime(2025, 1, 1, 22)) == "10PM"
        assert format_time_12hour(datetime(2025, 1, 1, 23)) == "11PM"

    def test_parse_time_12hour(self):
        """Test parsing 12-hour time strings."""
        # Morning hours
        assert parse_time_12hour("12AM") == 0
        assert parse_time_12hour("01AM") == 1
        assert parse_time_12hour("09AM") == 9
        assert parse_time_12hour("11AM") == 11

        # Afternoon hours
        assert parse_time_12hour("12PM") == 12
        assert parse_time_12hour("01PM") == 13
        assert parse_time_12hour("03PM") == 15
        assert parse_time_12hour("11PM") == 23

        # Case insensitive
        assert parse_time_12hour("02pm") == 14
        assert parse_time_12hour("08am") == 8

    def test_parse_time_12hour_invalid(self):
        """Test parsing invalid time strings."""
        with pytest.raises(ValueError):
            parse_time_12hour("25AM")

        with pytest.raises(ValueError):
            parse_time_12hour("12XM")

        with pytest.raises(ValueError):
            parse_time_12hour("invalid")

    def test_create_datetime_from_date_and_time(self):
        """Test creating datetime from date and time strings."""
        dt = create_datetime_from_date_and_time("2025-11-17", "02PM")
        assert dt.year == 2025
        assert dt.month == 11
        assert dt.day == 17
        assert dt.hour == 14
        assert dt.minute == 0


class TestTemperatureDescriptions:
    """Test temperature description functions."""

    def test_format_temperature_trend(self):
        """Test temperature trend formatting."""
        assert format_temperature_trend(32, 34) == "steady"  # Small difference
        assert format_temperature_trend(30, 40) == "rising"
        assert format_temperature_trend(40, 30) == "falling"
        assert format_temperature_trend(35, 35) == "steady"  # Same temperature

    def test_round_temperature_description(self):
        """Test temperature rounding descriptions."""
        assert round_temperature_description(72) == "around 70"
        assert round_temperature_description(78) == "around 80"
        assert round_temperature_description(75) == "the mid 70s"
        assert round_temperature_description(84) == "the mid 80s"

    def test_describe_temperature_range(self):
        """Test temperature range descriptions."""
        # Steady temperature
        desc = describe_temperature_range(32, 34)
        assert "steady" in desc.lower()

        # Rising temperature
        desc = describe_temperature_range(30, 45)
        assert "rising" in desc.lower()
        assert "starting" in desc.lower()

        # Falling temperature
        desc = describe_temperature_range(45, 30)
        assert "falling" in desc.lower()


class TestWeatherDescriptions:
    """Test weather description functions."""

    def test_normalize_weather_description(self):
        """Test weather description normalization."""
        assert normalize_weather_description("Sunny") == "Sunny"
        assert normalize_weather_description("AM Rain PM Sunny") == "Morning rain afternoon sunny"
        assert normalize_weather_description("PARTLY CLOUDY") == "Partly cloudy"
