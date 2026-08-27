"""Tests for apparent-temperature utility branches."""

from weather.utils.apparent_temperature import calculate_apparent_temperature


def test_none_temperature_returns_none():
    assert calculate_apparent_temperature(None) is None


def test_heat_index_uses_default_humidity():
    result = calculate_apparent_temperature(95)

    assert result > 95


def test_heat_index_calculates_humidity_from_celsius_dew_point():
    result = calculate_apparent_temperature(90, dew_point_c=20)

    assert result > 90


def test_heat_index_accepts_fahrenheit_dew_point():
    result = calculate_apparent_temperature(90, dew_point_f=68)

    assert result > 90


def test_moderate_temperature_returns_actual_temperature():
    assert calculate_apparent_temperature(70, humidity_pct=90, wind_speed_mph=2) == 70


def test_wind_chill_returns_lower_apparent_temperature():
    assert calculate_apparent_temperature(30, wind_speed_mph=15) < 30
