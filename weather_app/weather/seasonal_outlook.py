"""Seasonal analog outlook: what followed similar ENSO states at this place.

This is a *climatological analog* method, not a dynamical forecast, and its skill is low.
It looks at the latest published ENSO value (the ONI), finds past years whose ONI was
closest in the same calendar month, and reports what the following three months were like
at the place in those years compared with all years. Nothing is stored; it is computed on
demand from the ONI file and one Open-Meteo archive request (cached).

Only ENSO is used. PDO would be a natural second index, but its public file stopped
updating in 2025, so it is left out rather than shown stale.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from statistics import fmean
from typing import TYPE_CHECKING, Any

from django.core.cache import cache

from .climate_data import ARCHIVE_LAG_DAYS, WEATHER_URL, ClimateDataError, _get, _number

if TYPE_CHECKING:
    from .climate_data import IndexSeries

FIRST_YEAR = 1950
LEAD_MONTHS = 3
ANALOG_COUNT = 8
# Fewer comparable years than this and "closest analogs" means very little.
MIN_POOL_YEARS = 20
# A month needs nearly all its days to be summarized.
MIN_DAY_FRACTION = 0.9
MONTHLY_CACHE_SECONDS = 24 * 60 * 60
EL_NINO_THRESHOLD = 0.5

MonthKey = tuple[int, int]


class OutlookError(Exception):
    """The outlook could not be built from the available data."""


def enso_phase(value: float) -> str:
    """Name the ENSO state the way NOAA does (+/-0.5 C thresholds)."""
    if value >= EL_NINO_THRESHOLD:
        return "El Niño"
    if value <= -EL_NINO_THRESHOLD:
        return "La Niña"
    return "Neutral"


def aggregate_monthly(daily: dict[str, Any]) -> dict[MonthKey, dict[str, float]]:
    """Reduce archive daily data to {(year, month): mean temperature, total precipitation}."""
    times = daily.get("time") or []
    temps = daily.get("temperature_2m_mean") or []
    rain = daily.get("precipitation_sum") or []
    buckets: dict[MonthKey, dict[str, list[float]]] = {}
    for position, text in enumerate(times):
        try:
            day = date.fromisoformat(text)
        except ValueError:
            continue
        bucket = buckets.setdefault((day.year, day.month), {"t": [], "p": []})
        temp = _number(temps, position)
        precip = _number(rain, position)
        if temp is not None:
            bucket["t"].append(temp)
        if precip is not None:
            bucket["p"].append(precip)

    monthly: dict[MonthKey, dict[str, float]] = {}
    for (year, month), bucket in buckets.items():
        needed = calendar.monthrange(year, month)[1] * MIN_DAY_FRACTION
        if len(bucket["t"]) < needed or len(bucket["p"]) < needed:
            continue
        monthly[(year, month)] = {
            "temperature": fmean(bucket["t"]),
            "precipitation": sum(bucket["p"]),
        }
    return monthly


def fetch_monthly_weather(
    latitude: float, longitude: float
) -> dict[MonthKey, dict[str, float]]:
    """Monthly mean temperature (F) and total precipitation (in) since 1950, cached."""
    cache_key = f"seasonal-monthly:{latitude:.1f}:{longitude:.1f}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    end = date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
    params = {
        "latitude": round(latitude, 1),
        "longitude": round(longitude, 1),
        "start_date": f"{FIRST_YEAR}-01-01",
        "end_date": end.isoformat(),
        "daily": "temperature_2m_mean,precipitation_sum",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": "auto",
    }
    try:
        daily = _get(WEATHER_URL, params=params, timeout=60).json().get("daily") or {}
    except ValueError as exc:
        raise ClimateDataError("historical weather response was not JSON") from exc
    monthly = aggregate_monthly(daily)
    if not monthly:
        raise ClimateDataError("historical weather response had no monthly data")
    cache.set(cache_key, monthly, MONTHLY_CACHE_SECONDS)
    return monthly


def _following_months(year: int, month: int) -> list[MonthKey]:
    """The ``LEAD_MONTHS`` calendar months after (year, month)."""
    months = []
    for step in range(1, LEAD_MONTHS + 1):
        index = month - 1 + step
        months.append((year + index // 12, index % 12 + 1))
    return months


def _outcome(
    monthly: dict[MonthKey, dict[str, float]], year: int, month: int
) -> dict[str, float] | None:
    window = [monthly.get(key) for key in _following_months(year, month)]
    if any(entry is None for entry in window):
        return None
    return {
        "temperature": fmean(entry["temperature"] for entry in window if entry),
        "precipitation": sum(entry["precipitation"] for entry in window if entry),
    }


def build_outlook(
    oni: IndexSeries,
    monthly: dict[MonthKey, dict[str, float]],
    today: date,
    analog_count: int = ANALOG_COUNT,
) -> dict[str, Any]:
    """Summarize what followed the closest ENSO analog years at this place."""
    latest = oni.latest(today)
    if latest is None:
        raise OutlookError("No published ENSO value is available yet")
    as_of, current = latest

    candidates = []
    for year in range(FIRST_YEAR, as_of.year):
        value = oni.values.get((year, as_of.month))
        outcome = _outcome(monthly, year, as_of.month) if value is not None else None
        if outcome is not None:
            candidates.append({"year": year, "oni": value, **outcome})
    if len(candidates) < MIN_POOL_YEARS:
        raise OutlookError("Not enough history at this place to find analog years")

    climatology = {
        "temperature": fmean(c["temperature"] for c in candidates),
        "precipitation": fmean(c["precipitation"] for c in candidates),
    }
    analogs = sorted(candidates, key=lambda c: abs(c["oni"] - current))[:analog_count]
    analog_mean = {
        "temperature": fmean(a["temperature"] for a in analogs),
        "precipitation": fmean(a["precipitation"] for a in analogs),
    }
    months = _following_months(as_of.year, as_of.month)
    caveats = [
        "Analog-based and low skill: this shows what followed similar ENSO states "
        "in the past, not a forecast.",
        f"Only ENSO is considered, and only {len(analogs)} of {len(candidates)} "
        "past years are used. Other patterns can easily outweigh it.",
    ]
    lag = (today.year - as_of.year) * 12 + today.month - as_of.month
    if lag >= 2:
        caveats.append(
            f"The latest ENSO value is for {calendar.month_name[as_of.month]} "
            f"{as_of.year}, so the first of these months may already be over."
        )
    return {
        "enso": {
            "value": current,
            "phase": enso_phase(current),
            "as_of": as_of.isoformat(),
        },
        "target_months": [calendar.month_name[month] for _, month in months],
        "pool_years": len(candidates),
        "analog_years": analogs,
        "climatology": climatology,
        "analog_mean": analog_mean,
        "anomaly": {
            "temperature": analog_mean["temperature"] - climatology["temperature"],
            "precipitation": analog_mean["precipitation"]
            - climatology["precipitation"],
        },
        "agreement": {
            "count": len(analogs),
            "warmer": sum(
                1 for a in analogs if a["temperature"] > climatology["temperature"]
            ),
            "wetter": sum(
                1 for a in analogs if a["precipitation"] > climatology["precipitation"]
            ),
        },
        "caveats": caveats,
    }
