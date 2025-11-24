"""Date and time parsing utilities for weather data."""

from datetime import datetime, timezone as dt_timezone
from typing import Union, Optional
import re


def parse_nws_datetime(date_string: str) -> datetime:
    """Parse NWS API datetime strings to Python datetime objects."""
    # NWS typically returns ISO 8601 format with timezone
    # Examples: "2025-11-17T12:00:00-06:00" or "2025-11-17T18:00:00Z"

    if date_string.endswith('Z'):
        # UTC timezone
        date_string = date_string[:-1] + '+00:00'

    try:
        return datetime.fromisoformat(date_string)
    except ValueError as e:
        raise ValueError(f"Cannot parse NWS datetime string '{date_string}': {e}")


def format_time_12hour(dt: datetime) -> str:
    """Format datetime to 12-hour time string (e.g., '02PM', '11AM')."""
    hour = dt.hour

    if hour == 0:
        return "12AM"
    elif hour < 10:
        return f"0{hour}AM"
    elif hour < 12:
        return f"{hour}AM"
    elif hour == 12:
        return "12PM"
    elif hour < 22:
        return f"0{hour-12}PM"
    else:
        return f"{hour-12}PM"


def parse_time_12hour(time_str: str) -> int:
    """Parse 12-hour time string to hour (24-hour format)."""
    # Examples: "02PM" -> 14, "11AM" -> 11, "12AM" -> 0
    pattern = r'^(\d{1,2})(AM|PM)$'
    match = re.match(pattern, time_str.upper())

    if not match:
        raise ValueError(f"Invalid 12-hour time format: {time_str}")

    hour_str, period = match.groups()
    hour = int(hour_str)

    # Validate hour range
    if hour < 1 or hour > 12:
        raise ValueError(f"Invalid hour value: {hour}. Hour must be between 1 and 12")

    if period == "AM":
        if hour == 12:
            return 0
        else:
            return hour
    else:  # PM
        if hour == 12:
            return 12
        else:
            return hour + 12


def create_datetime_from_date_and_time(date_str: str, time_str: str) -> datetime:
    """Create datetime from separate date and time strings.

    Args:
        date_str: Date in format "YYYY-MM-DD"
        time_str: Time in 12-hour format like "02PM"

    Returns:
        datetime object (naive, local time)
    """
    hour_24 = parse_time_12hour(time_str)
    date_part = datetime.strptime(date_str, "%Y-%m-%d").date()
    return datetime.combine(date_part, datetime.min.time().replace(hour=hour_24))


def format_temperature_trend(am_temp: int, pm_temp: int) -> str:
    """Format temperature trend description."""
    diff = abs(am_temp - pm_temp)

    if diff <= 2:
        return "steady"
    elif am_temp < pm_temp:
        return "rising"
    else:
        return "falling"


def round_temperature_description(temp: int) -> str:
    """Create human-readable temperature description."""
    temp_str = str(temp)
    last_digit = int(temp_str[-1])

    if last_digit in [0, 1, 2]:
        return f"around {temp_str[:-1]}0"
    elif last_digit in [8, 9]:
        return f"around {str(int(temp_str[:-1])+1)}0"
    elif last_digit in [3, 4, 5, 6, 7]:
        return f"the mid {temp_str[:-1]}0s"


def describe_temperature_range(am_temp: int, pm_temp: int) -> str:
    """Create natural language description of daily temperature range."""
    am_desc = round_temperature_description(am_temp)
    pm_desc = round_temperature_description(pm_temp)
    trend = format_temperature_trend(am_temp, pm_temp)

    if trend == "steady":
        if am_temp < pm_temp:
            return f"holding steady {pm_desc}"
        else:
            return f"holding steady {am_desc}"
    else:
        if "the" in am_desc:
            return f"starting in {am_desc} and {trend} to {pm_desc}"
        else:
            return f"starting {am_desc} and {trend} to {pm_desc}"


def normalize_weather_description(weather: str) -> str:
    """Normalize weather descriptions for better readability."""
    words = weather.split()
    normalized_words = []

    for word in words:
        if word == "AM":
            normalized_words.append("morning")
        elif word == "PM":
            normalized_words.append("afternoon")
        else:
            normalized_words.append(word.lower())

    result = " ".join(normalized_words)
    return result.capitalize()


def is_dst_aware_datetime(dt: datetime) -> bool:
    """Check if datetime object is timezone-aware."""
    return dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None


def ensure_utc_datetime(dt: Union[datetime, str]) -> datetime:
    """Ensure datetime is in UTC timezone."""
    if isinstance(dt, str):
        dt = parse_nws_datetime(dt)

    if not is_dst_aware_datetime(dt):
        # Assume local time if naive
        dt = dt.replace(tzinfo=dt_timezone.utc)
    else:
        # Convert to UTC
        dt = dt.astimezone(dt_timezone.utc)

    return dt


def format_date_for_display(dt: datetime, include_day_name: bool = True) -> str:
    """Format date for user display."""
    if include_day_name:
        return dt.strftime("%A, %B %d, %Y")
    else:
        return dt.strftime("%B %d, %Y")


def days_relative_name(days_from_today: int) -> str:
    """Get relative day name (Today, Tomorrow, etc.)."""
    if days_from_today == 0:
        return "Today"
    elif days_from_today == 1:
        return "Tomorrow"
    elif days_from_today == -1:
        return "Yesterday"
    else:
        return f"In {days_from_today} days" if days_from_today > 0 else f"{abs(days_from_today)} days ago"
