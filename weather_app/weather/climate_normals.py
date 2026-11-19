"""Climate normals: the 1991-2020 average high, low and precipitation for a place.

Computed on demand from the Open-Meteo Archive (ERA5-based reanalysis), so they are an
average *at this location*, not NOAA's official station normals. Nothing is stored; the
small per-calendar-day result is kept in the process-local cache.

Each calendar day's value averages that day across the 30 years, then smooths over a
centered 7-day window so single noisy days do not dominate.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from django.core.cache import cache

from .upstream import get_json

if TYPE_CHECKING:
    from collections.abc import Iterable

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FIRST_YEAR = 1991
LAST_YEAR = 2020
PERIOD = f"{FIRST_YEAR}-{LAST_YEAR}"
HALF_WINDOW = 3
# A calendar day needs this many years of data; Feb 29 (8 leap years) is filled from
# its neighbors by the smoothing instead.
MIN_YEARS = 20
NORMALS_CACHE_SECONDS = 7 * 24 * 60 * 60
# Nearby requests share one archive call: coordinates are rounded to this many places.
COORDINATE_PLACES = 1
_REFERENCE_YEAR = 2000  # a leap year, so every calendar day exists
_FIELDS = ("temperature_2m_max", "temperature_2m_min", "precipitation_sum")

DayKey = tuple[int, int]
Normal = dict[str, float | None]


class ClimateNormalsError(Exception):
    """Normals could not be fetched or computed."""


def _ordinal(key: DayKey) -> int:
    return date(_REFERENCE_YEAR, key[0], key[1]).toordinal()


def _key(ordinal: int) -> DayKey:
    day = date.fromordinal(ordinal)
    return (day.month, day.day)


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def compute_daily_normals(daily: dict[str, Any]) -> dict[DayKey, Normal]:
    """Reduce an archive ``daily`` block to smoothed {(month, day): normals}."""
    times = daily.get("time") or []
    columns = {name: daily.get(name) or [] for name in _FIELDS}
    samples: dict[DayKey, dict[str, list[float]]] = defaultdict(
        lambda: {name: [] for name in _FIELDS}
    )
    for position, text in enumerate(times):
        try:
            observed = date.fromisoformat(text)
        except ValueError:
            continue
        if not FIRST_YEAR <= observed.year <= LAST_YEAR:
            continue
        for name, values in columns.items():
            value = values[position] if position < len(values) else None
            if value is not None:
                samples[(observed.month, observed.day)][name].append(float(value))

    # Mean across years for each calendar day with enough years of data.
    raw: dict[DayKey, Normal] = {}
    for key, fields in samples.items():
        if all(len(values) >= MIN_YEARS for values in fields.values()):
            raw[key] = {name: _mean(values) for name, values in fields.items()}

    # Smooth over a centered window around every calendar day (Dec wraps into Jan).
    year_start = date(_REFERENCE_YEAR, 1, 1).toordinal()
    days_in_year = 366
    smoothed: dict[DayKey, Normal] = {}
    for offset in range(days_in_year):
        window = []
        for shift in range(-HALF_WINDOW, HALF_WINDOW + 1):
            neighbor = _key(year_start + (offset + shift) % days_in_year)
            if neighbor in raw:
                window.append(raw[neighbor])
        if window:
            smoothed[_key(year_start + offset)] = {
                name: _mean(entry[name] for entry in window) for name in _FIELDS
            }
    return smoothed


def fetch_daily_normals(latitude: float, longitude: float) -> dict[DayKey, Normal]:
    """Return 1991-2020 daily normals for a place, cached by rounded coordinates."""
    latitude = round(latitude, COORDINATE_PLACES)
    longitude = round(longitude, COORDINATE_PLACES)
    cache_key = f"climate-daily-normals:{latitude}:{longitude}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        payload = get_json(
            ARCHIVE_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "start_date": f"{FIRST_YEAR}-01-01",
                "end_date": f"{LAST_YEAR}-12-31",
                "daily": ",".join(_FIELDS),
                "temperature_unit": "fahrenheit",
                "precipitation_unit": "inch",
                "timezone": "auto",
            },
            timeout=60,
        )
    except Exception as exc:
        raise ClimateNormalsError(f"historical weather request failed: {exc}") from exc

    normals = compute_daily_normals(payload.get("daily") or {})
    if not normals:
        raise ClimateNormalsError("historical weather response had no usable data")
    cache.set(cache_key, normals, NORMALS_CACHE_SECONDS)
    return normals


def normals_for_dates(
    normals: dict[DayKey, Normal], start: date, days: int
) -> list[dict[str, Any]]:
    """The normals for ``days`` consecutive dates beginning at ``start``."""
    result = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        entry = normals.get((day.month, day.day))
        if entry is None:
            continue
        result.append(
            {
                "date": day.isoformat(),
                "high": _round(entry["temperature_2m_max"]),
                "low": _round(entry["temperature_2m_min"]),
                "precipitation": _round(entry["precipitation_sum"], 2),
            }
        )
    return result


def _round(value: float | None, places: int = 1) -> float | None:
    return round(value, places) if value is not None else None
