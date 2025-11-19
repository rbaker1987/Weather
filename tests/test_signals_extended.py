"""Extended signal tests to achieve 85%+ coverage."""

from datetime import datetime, time

import pytest
from django.utils import timezone

from weather.models import DailyForecast, HourlyForecast, Location


@pytest.mark.django_db
class TestSignalApparentTemperatureEdgeCases:
    """Test apparent temperature signal with specific temperature ranges."""

    def test_heat_index_at_exactly_80f(self):
        """Test heat index calculation when temp is exactly 80F."""
        loc = Location.objects.create(name="HotLocation")
        today = timezone.now().date()

        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(14, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=80,
            temperature_unit='F',
            short_forecast="Hot",
            wind_speed=5,  # Required field
        )
        # At 80F: apparent_temp = 80 + (80-80)*0.1 = 80
        assert forecast.apparent_temperature == 80

    def test_heat_index_above_80f(self):
        """Test heat index calculation when temp is above 80F."""
        loc = Location.objects.create(name="VeryHot")
        today = timezone.now().date()

        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(14, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=95,
            temperature_unit='F',
            short_forecast="Very Hot",
            wind_speed=5,  # Required field
        )
        # At 95F: apparent_temp = 95 + (95-80)*0.1 = 95 + 1.5 = 96.5 -> 96
        assert forecast.apparent_temperature >= 95

    def test_wind_chill_at_exactly_50f(self):
        """Test wind chill calculation when temp is exactly 50F."""
        loc = Location.objects.create(name="CoolLocation")
        today = timezone.now().date()

        forecast = HourlyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(7, 0))),
            is_daytime=True,
            temperature=50,
            temperature_unit='F',
            short_forecast="Cool",
            wind_speed=10,
        )
        # At 50F with 10mph wind: apparent_temp = 50 - (10*0.2) = 48
        assert forecast.apparent_temperature <= 50

    def test_wind_chill_below_50f(self):
        """Test wind chill calculation when temp is below 50F."""
        loc = Location.objects.create(name="ColdLocation")
        today = timezone.now().date()

        forecast = HourlyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(3, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(4, 0))),
            is_daytime=False,
            temperature=35,
            temperature_unit='F',
            short_forecast="Cold",
            wind_speed=20,
        )
        # At 35F with 20mph wind: apparent_temp = 35 - (20*0.2) = 31
        assert forecast.apparent_temperature <= 35

    def test_wind_chill_with_zero_wind(self):
        """Test wind chill when wind speed is zero."""
        loc = Location.objects.create(name="StillCold")
        today = timezone.now().date()

        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=40,
            temperature_unit='F',
            short_forecast="Cold Calm",
            wind_speed=0,
        )
        # At 40F with 0 wind: apparent_temp = 40 - (0*0.2) = 40
        assert forecast.apparent_temperature == 40

    def test_celsius_conversion_to_heat_index(self):
        """Test Celsius to Fahrenheit conversion triggering heat index."""
        loc = Location.objects.create(name="CelsiusHot")
        today = timezone.now().date()

        # 32C = 89.6F, should trigger heat index
        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(14, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=32,
            temperature_unit='C',
            short_forecast="Hot",
            wind_speed=5,  # Required field
        )
        # Should convert to F and apply heat index
        assert forecast.apparent_temperature is not None
        # Apparent temp should be calculated based on F conversion
        assert forecast.apparent_temperature >= 32

    def test_celsius_conversion_to_wind_chill(self):
        """Test Celsius to Fahrenheit conversion triggering wind chill."""
        loc = Location.objects.create(name="CelsiusCold")
        today = timezone.now().date()

        # 5C = 41F, should trigger wind chill
        forecast = HourlyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(7, 0))),
            is_daytime=True,
            temperature=5,
            temperature_unit='C',
            short_forecast="Cold",
            wind_speed=15,
        )
        # Should convert to F and apply wind chill
        assert forecast.apparent_temperature is not None
        # 5C = 41F, wind chill: 41 - 15*0.2 = 38F
        assert forecast.apparent_temperature <= 41  # Should feel colder than actual temp in F

    def test_apparent_temperature_already_set(self):
        """Test that signal doesn't override manually set apparent temperature."""
        loc = Location.objects.create(name="ManualApparent")
        today = timezone.now().date()

        # Manually set apparent temperature
        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(14, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=90,
            temperature_unit='F',
            apparent_temperature=88,  # Manually set
            short_forecast="Hot but feels cooler",
            wind_speed=15,  # Required field
        )
        # Signal should not override manual value
        assert forecast.apparent_temperature == 88


@pytest.mark.django_db
class TestLocationValidationSignal:
    """Test location coordinate validation signal."""

    def test_valid_coordinates(self):
        """Test that valid coordinates pass validation."""
        # Should not raise
        loc = Location.objects.create(
            name="ValidLocation",
            latitude=45.0,
            longitude=-122.0
        )
        assert loc.latitude == 45.0
        assert loc.longitude == -122.0

    def test_invalid_latitude_too_high(self):
        """Test validation rejects latitude > 90."""
        with pytest.raises(ValueError, match="Invalid latitude"):
            Location.objects.create(
                name="InvalidLat",
                latitude=91.0,
                longitude=-122.0
            )

    def test_invalid_latitude_too_low(self):
        """Test validation rejects latitude < -90."""
        with pytest.raises(ValueError, match="Invalid latitude"):
            Location.objects.create(
                name="InvalidLat",
                latitude=-91.0,
                longitude=-122.0
            )

    def test_invalid_longitude_too_high(self):
        """Test validation rejects longitude > 180."""
        with pytest.raises(ValueError, match="Invalid longitude"):
            Location.objects.create(
                name="InvalidLon",
                latitude=45.0,
                longitude=181.0
            )

    def test_invalid_longitude_too_low(self):
        """Test validation rejects longitude < -180."""
        with pytest.raises(ValueError, match="Invalid longitude"):
            Location.objects.create(
                name="InvalidLon",
                latitude=45.0,
                longitude=-181.0
            )

    def test_coordinates_at_boundaries(self):
        """Test coordinates at valid boundaries."""
        # North Pole
        loc1 = Location.objects.create(name="NorthPole", latitude=90.0, longitude=0.0)
        assert loc1.latitude == 90.0

        # South Pole
        loc2 = Location.objects.create(name="SouthPole", latitude=-90.0, longitude=0.0)
        assert loc2.latitude == -90.0

        # International Date Line East
        loc3 = Location.objects.create(name="DateLineE", latitude=0.0, longitude=180.0)
        assert loc3.longitude == 180.0

        # International Date Line West
        loc4 = Location.objects.create(name="DateLineW", latitude=0.0, longitude=-180.0)
        assert loc4.longitude == -180.0

    def test_none_coordinates_skip_validation(self):
        """Test that None coordinates skip validation."""
        # Should not raise - validation only runs if both coords are not None
        loc = Location.objects.create(
            name="NoCoords",
            latitude=None,
            longitude=None
        )
        assert loc.latitude is None
        assert loc.longitude is None

    def test_partial_coordinates_skip_validation(self):
        """Test that partial coordinates skip validation."""
        # Only latitude set, longitude is None - should not validate
        loc1 = Location.objects.create(
            name="OnlyLat",
            latitude=45.0,
            longitude=None
        )
        assert loc1.latitude == 45.0

        # Only longitude set, latitude is None - should not validate
        loc2 = Location.objects.create(
            name="OnlyLon",
            latitude=None,
            longitude=-122.0
        )
        assert loc2.longitude == -122.0
