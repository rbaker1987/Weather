"""Tests for the Pydantic weather domain models."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from weather.core.models import (
    DailyForecast,
    HourlyForecast,
    Location,
    Temperature,
    TemperatureUnit,
    WeatherAlert,
    WeatherCondition,
    WeatherReport,
    WindCondition,
)


def make_hourly(hour, temperature=70, condition="Sunny"):
    return HourlyForecast(
        location=Location(name="Austin"),
        forecast_time=datetime(2026, 8, 22, hour, tzinfo=timezone.utc),
        temperature=Temperature(value=temperature),
        wind=WindCondition(speed=8, direction="N", gust=15),
        weather=WeatherCondition(short_forecast=condition),
    )


def test_location_normalizes_and_validates_values():
    location = Location(name="  austin, tx  ", zip_code="78701")

    assert location.name == "Austin, Tx"

    with pytest.raises(ValidationError):
        Location(name="", latitude=91)


def test_temperature_apparent_temperature_branches():
    warm = Temperature(value=70)
    cold = Temperature(value=30)
    celsius = Temperature(value=20, unit=TemperatureUnit.CELSIUS)

    assert warm.apparent_temperature(20) == 70
    assert cold.apparent_temperature(3) == 30
    assert cold.apparent_temperature(20) < 30
    with pytest.raises(ValueError, match="Fahrenheit"):
        celsius.apparent_temperature(10)


def test_wind_condition_validates_nonnegative_values():
    with pytest.raises(ValidationError):
        WindCondition(speed=-1)


def test_hourly_forecast_properties_and_time_formats():
    assert make_hourly(0).time_12h == "12AM"
    assert make_hourly(9).time_12h == "09AM"
    assert make_hourly(11).time_12h == "11AM"
    assert make_hourly(12).time_12h == "12PM"
    assert make_hourly(15).time_12h == "03PM"
    assert make_hourly(22).time_12h == "10PM"

    forecast = make_hourly(12, temperature=40, condition="Cloudy")
    assert forecast.period_start == forecast.forecast_time
    assert forecast.period_end > forecast.period_start
    assert forecast.date == date(2026, 8, 22)
    assert forecast.short_forecast == "Cloudy"
    assert forecast.detailed_forecast is None
    assert forecast.apparent_temperature < 40


def test_daily_forecast_aggregates_and_prefers_noon_weather():
    morning = make_hourly(7, temperature=55, condition="Fog")
    noon = make_hourly(12, temperature=75, condition="Sunny")
    daily = DailyForecast(
        date=date(2026, 8, 22),
        location=Location(name="Austin"),
        hourly_forecasts=[morning, noon],
    )

    assert daily.high_temperature == 75
    assert daily.low_temperature == 55
    assert daily.primary_weather == "Sunny"

    empty = DailyForecast(date=date(2026, 8, 22), location=Location(name="Austin"))
    assert empty.high_temperature is None
    assert empty.low_temperature is None
    assert empty.primary_weather is None


def test_weather_report_filters_forecasts_case_insensitively():
    forecast = DailyForecast(
        date=date(2026, 8, 22),
        location=Location(name="Austin"),
        hourly_forecasts=[],
    )
    report = WeatherReport(locations=[Location(name="Austin")], daily_forecasts=[forecast])

    assert report.get_forecasts_for_location("AUSTIN") == [forecast]
    assert report.get_forecasts_for_location("Dallas") == []


def test_weather_alert_requires_start_time():
    alert = WeatherAlert(
        event="Heat Advisory",
        start_time=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )

    assert alert.end_time is None
    assert alert.severity is None
