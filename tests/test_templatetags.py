"""Tests for template tags."""

from weather.templatetags.ui_tags import condition_icon, temp_bg_class


class TestConditionIcon:
    """Test condition_icon template filter."""

    def test_none_returns_default(self):
        """Test that None returns default cloud-sun icon."""
        assert condition_icon(None) == "cloud-sun"

    def test_empty_string_returns_default(self):
        """Test that empty string returns default icon."""
        assert condition_icon("") == "cloud-sun"

    def test_storm_keywords(self):
        """Test storm-related keywords return bolt icon."""
        assert condition_icon("Thunderstorm") == "bolt"
        assert condition_icon("T-Storm") == "bolt"
        assert condition_icon("storm") == "bolt"

    def test_ice_keywords(self):
        """Test ice-related keywords return icicles icon."""
        assert condition_icon("Icy conditions") == "icicles"
        assert condition_icon("Freezing rain") == "icicles"
        assert condition_icon("Sleet") == "icicles"

    def test_snow_keywords(self):
        """Test snow-related keywords return snowflake icon."""
        assert condition_icon("Snow") == "snowflake"
        assert condition_icon("Flurries") == "snowflake"
        assert condition_icon("Blizzard") == "snowflake"

    def test_fog_keywords(self):
        """Test fog-related keywords return smog icon."""
        assert condition_icon("Fog") == "smog"
        assert condition_icon("Mist") == "smog"
        assert condition_icon("Haze") == "smog"

    def test_rain_keywords(self):
        """Test rain-related keywords return cloud-rain icon."""
        assert condition_icon("Rain") == "cloud-rain"
        assert condition_icon("Shower") == "cloud-rain"
        assert condition_icon("Drizzle") == "cloud-rain"

    def test_wind_keyword(self):
        """Test wind keyword returns wind icon."""
        assert condition_icon("Windy") == "wind"

    def test_windy_and_cloudy_not_wind_icon(self):
        """Test that 'windy and cloudy' doesn't return wind icon."""
        # "wind" + "cloudy" should skip wind icon check
        assert condition_icon("Windy and cloudy") == "cloud"

    def test_partly_keyword(self):
        """Test partly keyword returns cloud-sun icon."""
        assert condition_icon("Partly cloudy") == "cloud-sun"

    def test_sunny_keywords(self):
        """Test sunny/clear/fair keywords return sun icon."""
        assert condition_icon("Sunny") == "sun"
        assert condition_icon("Clear") == "sun"
        assert condition_icon("Fair") == "sun"

    def test_cloudy_keywords(self):
        """Test cloudy/overcast keywords return cloud icon."""
        assert condition_icon("Cloudy") == "cloud"
        assert condition_icon("Overcast") == "cloud"

    def test_unknown_condition_returns_default(self):
        """Test unknown conditions return default icon."""
        assert condition_icon("Unknown weather") == "cloud-sun"

    def test_case_insensitive(self):
        """Test that matching is case-insensitive."""
        assert condition_icon("THUNDERSTORM") == "bolt"
        assert condition_icon("RaIn") == "cloud-rain"


class TestTempBgClass:
    """Test temp_bg_class template filter."""

    def test_valid_integer(self):
        """Test valid integer returns correct class."""
        assert temp_bg_class(75) == "temp-bg-75"

    def test_valid_string_integer(self):
        """Test valid string integer returns correct class."""
        assert temp_bg_class("85") == "temp-bg-85"

    def test_negative_temperature(self):
        """Test negative temperature works."""
        assert temp_bg_class(-10) == "temp-bg--10"

    def test_zero_temperature(self):
        """Test zero temperature works."""
        assert temp_bg_class(0) == "temp-bg-0"

    def test_none_returns_empty(self):
        """Test None returns empty string."""
        assert temp_bg_class(None) == ""

    def test_invalid_string_returns_empty(self):
        """Test invalid string returns empty string."""
        assert temp_bg_class("not a number") == ""

    def test_float_converts_to_int(self):
        """Test float is converted to int."""
        assert temp_bg_class(75.8) == "temp-bg-75"

    def test_empty_string_returns_empty(self):
        """Test empty string returns empty string."""
        assert temp_bg_class("") == ""
