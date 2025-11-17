"""Tests for core weather models."""

import pytest
from datetime import datetime

from weather_app.core.models import (
    Location, Temperature, WindCondition, WeatherCondition, 
    HourlyForecast, TemperatureUnit
)


class TestLocation:
    """Test the Location model."""
    
    def test_location_creation(self):
        """Test basic location creation."""
        location = Location(
            name="Austin, TX",
            latitude=30.2672,
            longitude=-97.7431
        )
        
        assert location.name == "Austin, TX"
        assert location.latitude == 30.2672
        assert location.longitude == -97.7431
    
    def test_location_name_validation(self):
        """Test location name validation."""
        with pytest.raises(ValueError, match="Location name cannot be empty"):
            Location(name="   ")
    
    def test_location_coordinate_validation(self):
        """Test coordinate validation."""
        with pytest.raises(ValueError):
            Location(name="Test", latitude=100)  # Invalid latitude
        
        with pytest.raises(ValueError):
            Location(name="Test", longitude=200)  # Invalid longitude


class TestTemperature:
    """Test the Temperature model."""
    
    def test_temperature_creation(self):
        """Test basic temperature creation."""
        temp = Temperature(value=75)
        assert temp.value == 75
        assert temp.unit == TemperatureUnit.FAHRENHEIT
    
    def test_apparent_temperature_warm(self):
        """Test apparent temperature calculation for warm weather."""
        temp = Temperature(value=75)
        apparent = temp.apparent_temperature(wind_speed=3)
        assert apparent == 75  # No wind chill for warm temp and low wind
    
    def test_apparent_temperature_cold(self):
        """Test apparent temperature calculation for cold weather."""
        temp = Temperature(value=32)
        apparent = temp.apparent_temperature(wind_speed=15)
        assert apparent < 32  # Should be colder due to wind chill


class TestHourlyForecast:
    """Test the HourlyForecast model."""
    
    def test_forecast_creation(self, sample_location):
        """Test forecast creation."""
        forecast = HourlyForecast(
            location=sample_location,
            forecast_time=datetime(2025, 11, 17, 14, 0),
            temperature=Temperature(value=72),
            wind=WindCondition(speed=8, direction="NW"),
            weather=WeatherCondition(short_forecast="Sunny")
        )
        
        assert forecast.location.name == "Austin, TX"
        assert forecast.temperature.value == 72
        assert forecast.wind.speed == 8
        assert forecast.weather.short_forecast == "Sunny"
    
    def test_time_12h_property(self, sample_location):
        """Test 12-hour time formatting."""
        # Test morning
        forecast_am = HourlyForecast(
            location=sample_location,
            forecast_time=datetime(2025, 11, 17, 9, 0),
            temperature=Temperature(value=65),
            wind=WindCondition(speed=5),
            weather=WeatherCondition(short_forecast="Clear")
        )
        assert forecast_am.time_12h == "09AM"
        
        # Test afternoon
        forecast_pm = HourlyForecast(
            location=sample_location,
            forecast_time=datetime(2025, 11, 17, 15, 0),
            temperature=Temperature(value=78),
            wind=WindCondition(speed=5),
            weather=WeatherCondition(short_forecast="Clear")
        )
        assert forecast_pm.time_12h == "03PM"
        
        # Test midnight
        forecast_midnight = HourlyForecast(
            location=sample_location,
            forecast_time=datetime(2025, 11, 17, 0, 0),
            temperature=Temperature(value=58),
            wind=WindCondition(speed=5),
            weather=WeatherCondition(short_forecast="Clear")
        )
        assert forecast_midnight.time_12h == "12AM"
    
    def test_apparent_temperature_property(self, sample_location):
        """Test apparent temperature property."""
        forecast = HourlyForecast(
            location=sample_location,
            forecast_time=datetime(2025, 11, 17, 12, 0),
            temperature=Temperature(value=32),
            wind=WindCondition(speed=20),
            weather=WeatherCondition(short_forecast="Windy")
        )
        
        apparent = forecast.apparent_temperature
        assert apparent < 32  # Should be lower due to wind chill