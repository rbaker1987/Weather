"""Tests for signals: coordinate validation and apparent temperature calculations."""
from datetime import datetime, time
from decimal import Decimal

import pytest
from django.utils import timezone

from weather.models import DailyForecast, HourlyForecast, Location


@pytest.mark.django_db
class TestLocationSignals:
    def test_coordinate_validation_valid(self):
        loc = Location.objects.create(name="Valid", latitude=Decimal("45.5"), longitude=Decimal("-122.6"))
        assert loc.latitude == Decimal("45.5")

    def test_coordinate_validation_invalid_latitude(self):
        with pytest.raises(ValueError, match="Invalid latitude"):
            Location.objects.create(name="BadLat", latitude=Decimal("91.0"), longitude=Decimal("0.0"))

    def test_coordinate_validation_invalid_longitude(self):
        with pytest.raises(ValueError, match="Invalid longitude"):
            Location.objects.create(name="BadLon", latitude=Decimal("0.0"), longitude=Decimal("181.0"))

    def test_latitude_at_minimum_boundary(self):
        loc = Location.objects.create(name="SouthPole", latitude=Decimal("-90.0"), longitude=Decimal("0.0"))
        assert loc.latitude == Decimal("-90.0")

    def test_latitude_at_maximum_boundary(self):
        loc = Location.objects.create(name="NorthPole", latitude=Decimal("90.0"), longitude=Decimal("0.0"))
        assert loc.latitude == Decimal("90.0")

    def test_latitude_below_minimum(self):
        with pytest.raises(ValueError, match="Invalid latitude"):
            Location.objects.create(name="TooSouth", latitude=Decimal("-90.1"), longitude=Decimal("0.0"))

    def test_latitude_above_maximum(self):
        with pytest.raises(ValueError, match="Invalid latitude"):
            Location.objects.create(name="TooNorth", latitude=Decimal("90.1"), longitude=Decimal("0.0"))

    def test_longitude_at_minimum_boundary(self):
        loc = Location.objects.create(name="DatelineWest", latitude=Decimal("0.0"), longitude=Decimal("-180.0"))
        assert loc.longitude == Decimal("-180.0")

    def test_longitude_at_maximum_boundary(self):
        loc = Location.objects.create(name="DatelineEast", latitude=Decimal("0.0"), longitude=Decimal("180.0"))
        assert loc.longitude == Decimal("180.0")

    def test_longitude_below_minimum(self):
        with pytest.raises(ValueError, match="Invalid longitude"):
            Location.objects.create(name="TooWest", latitude=Decimal("0.0"), longitude=Decimal("-180.1"))

    def test_longitude_above_maximum(self):
        with pytest.raises(ValueError, match="Invalid longitude"):
            Location.objects.create(name="TooEast", latitude=Decimal("0.0"), longitude=Decimal("180.1"))

    def test_coordinates_both_invalid(self):
        with pytest.raises(ValueError):
            Location.objects.create(name="BothInvalid", latitude=Decimal("100.0"), longitude=Decimal("200.0"))


@pytest.mark.django_db
class TestForecastSignals:
    def test_apparent_temperature_calculated(self):
        loc = Location.objects.create(name="Test")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=85,
            short_forecast="Hot",
            wind_speed=5,
        )
        assert forecast.apparent_temperature is not None
        assert forecast.apparent_temperature >= 85

    def test_heat_index_at_exactly_80f(self):
        loc = Location.objects.create(name="HotLocation")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(14, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=80,
            temperature_unit="F",
            short_forecast="Hot",
            wind_speed=5,
        )
        assert forecast.apparent_temperature == 80

    def test_heat_index_above_80f(self):
        loc = Location.objects.create(name="VeryHot")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(14, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=95,
            temperature_unit="F",
            short_forecast="Very Hot",
            wind_speed=5,
        )
        assert forecast.apparent_temperature >= 95

    def test_wind_chill_at_exactly_50f(self):
        loc = Location.objects.create(name="CoolLocation")
        today = timezone.now().date()
        forecast = HourlyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(7, 0))),
            is_daytime=True,
            temperature=50,
            temperature_unit="F",
            short_forecast="Cool",
            wind_speed=10,
        )
        assert forecast.apparent_temperature <= 50

    def test_wind_chill_below_50f(self):
        loc = Location.objects.create(name="ColdLocation")
        today = timezone.now().date()
        forecast = HourlyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(3, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(4, 0))),
            is_daytime=False,
            temperature=35,
            temperature_unit="F",
            short_forecast="Cold",
            wind_speed=20,
        )
        assert forecast.apparent_temperature <= 35

    def test_wind_chill_with_zero_wind(self):
        loc = Location.objects.create(name="StillCold")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=40,
            temperature_unit="F",
            short_forecast="Cold Calm",
            wind_speed=0,
        )
        assert forecast.apparent_temperature == 40

    def test_celsius_conversion_to_heat_index(self):
        loc = Location.objects.create(name="CelsiusHot")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(14, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=32,
            temperature_unit="C",
            short_forecast="Hot",
            wind_speed=5,
        )
        assert forecast.apparent_temperature is not None
        assert forecast.apparent_temperature >= 32

    def test_celsius_conversion_to_wind_chill(self):
        loc = Location.objects.create(name="CelsiusCold")
        today = timezone.now().date()
        forecast = HourlyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(7, 0))),
            is_daytime=True,
            temperature=5,
            temperature_unit="C",
            short_forecast="Cold",
            wind_speed=15,
        )
        assert forecast.apparent_temperature is not None
        assert forecast.apparent_temperature <= 41

    def test_apparent_temperature_already_set(self):
        loc = Location.objects.create(name="ManualApparent")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(14, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=90,
            temperature_unit="F",
            apparent_temperature=88,
            short_forecast="Hot but feels cooler",
            wind_speed=15,
        )
        assert forecast.apparent_temperature == 88

    def test_apparent_temperature_moderate(self):
        loc = Location.objects.create(name="Moderate")
        today = timezone.now().date()
        forecast = DailyForecast.objects.create(
            location=loc,
            forecast_date=today,
            period_start=timezone.make_aware(datetime.combine(today, time(6, 0))),
            period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
            is_daytime=True,
            temperature=65,
            short_forecast="Pleasant",
            wind_speed=5,
        )
        assert forecast.apparent_temperature == 65
