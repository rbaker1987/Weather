"""Tests for uncovered UI template-tag branches."""

from dataclasses import dataclass

import pytest

from weather.templatetags.ui_tags import (
    condition_icon,
    is_mixed_precip,
    is_snow_precip,
    needs_chance_layout,
    pop_icon,
    round_pop,
    should_show_feels_like,
)


@dataclass
class Forecast:
    short_forecast: str
    precipitation_probability: object = None
    is_daytime: bool = True
    temperature: object = 70
    apparent_temperature: object = 70


@pytest.mark.parametrize(
    ("condition", "pop", "daytime", "expected"),
    [
        ("Thunderstorm", 50, True, "bolt"),
        ("Snow", 50, True, "snowflake"),
        ("Rain", 50, True, "tint"),
        ("Snow", 20, True, "cloud-snow"),
        ("Rain", 20, True, "cloud-rain"),
        ("Partly cloudy", 5, False, "cloud-moon"),
        ("Clear", 5, False, "moon"),
        ("Cloudy", 5, True, "cloud"),
    ],
)
def test_condition_icon_uses_probability_and_daylight_branches(
    condition, pop, daytime, expected
):
    assert condition_icon(Forecast(condition, pop, daytime), "night") == expected


def test_condition_icon_accepts_text_and_boolean_period_type():
    assert condition_icon("Partly cloudy", False) == "cloud-moon"
    assert condition_icon(None, False) == "cloud-moon"


@pytest.mark.parametrize(
    ("actual", "apparent", "expected"),
    [(70, 70, False), (70, 64, True), (None, 60, False), ("bad", 60, False)],
)
def test_should_show_feels_like_accepts_separate_values(actual, apparent, expected):
    assert should_show_feels_like(actual, apparent) is expected


def test_should_show_feels_like_accepts_forecast_object():
    assert should_show_feels_like(Forecast("Sunny", temperature=70, apparent_temperature=60))


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (14, 10), (15, 20), (26, 30), ("bad", "bad")],
)
def test_round_pop_handles_values(value, expected):
    assert round_pop(value) == expected


def test_pop_icon_is_constant():
    assert pop_icon(80, "Rain") == "tint"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(Forecast("Snow", 20), "snow"), (Forecast("Thunderstorm", 20), "storm")],
)
def test_needs_chance_layout_for_snow_and_storm(value, expected):
    assert needs_chance_layout(value) == expected


def test_needs_chance_layout_handles_invalid_inputs():
    assert needs_chance_layout("Snow") == ""
    assert needs_chance_layout(Forecast("Snow", "bad")) == ""
    assert needs_chance_layout(Forecast("Snow")) == ""


def test_precipitation_filters_handle_objects_and_none():
    assert is_snow_precip(Forecast("Light snow", 30)) is True
    assert is_snow_precip(None) is False
    assert is_mixed_precip(Forecast("Rain and snow", 50)) is False
    assert is_mixed_precip(None) is False
