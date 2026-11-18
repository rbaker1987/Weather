"""How much do the forecast models agree? Pure computation, no I/O.

Takes the per-model results of ``ModelComparisonAPIView.fetch_all_models`` (hourly
temperature in F and precipitation in mm, in the place's local time) and reduces them
to one row per local calendar day: the min / median / max across models of the daily
high, low and precipitation total, plus a plain-language agreement level.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

MM_PER_INCH = 25.4
# A model day needs nearly a full day of hourly values or its high/low/total is biased.
MIN_HOURS_PER_DAY = 20

# (high-agreement limit, moderate-agreement limit): spreads above the second are "low".
TEMPERATURE_SPREAD_F = (3.0, 6.0)
PRECIPITATION_SPREAD_IN = (0.05, 0.25)

_LEVEL_ORDER = {"high": 0, "moderate": 1, "low": 2}


def agreement_level(spread: float, limits: tuple[float, float]) -> str:
    """Classify a spread: ``high`` / ``moderate`` / ``low`` agreement."""
    if spread <= limits[0]:
        return "high"
    if spread <= limits[1]:
        return "moderate"
    return "low"


def _daily_values(hourly: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Return {date: {"high", "low", "precip_in"}} for fully covered days."""
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    precips = hourly.get("precipitation") or []
    by_day_temp: dict[str, list[float]] = defaultdict(list)
    by_day_precip: dict[str, list[float]] = defaultdict(list)
    for position, stamp in enumerate(times):
        day = str(stamp)[:10]
        if position < len(temps) and temps[position] is not None:
            by_day_temp[day].append(float(temps[position]))
        if position < len(precips) and precips[position] is not None:
            by_day_precip[day].append(float(precips[position]))

    days: dict[str, dict[str, float]] = {}
    for day, values in by_day_temp.items():
        if len(values) < MIN_HOURS_PER_DAY:
            continue
        entry = {"high": max(values), "low": min(values)}
        rain = by_day_precip.get(day, [])
        if len(rain) >= MIN_HOURS_PER_DAY:
            entry["precip_in"] = sum(rain) / MM_PER_INCH
        days[day] = entry
    return days


def _summarize(values: dict[str, float], limits: tuple[float, float], digits: int):
    """Min / median / max / spread across models for one variable on one day."""
    ordered = sorted(values.values())
    mid = median(ordered)
    spread = ordered[-1] - ordered[0]
    level = agreement_level(spread, limits)
    outlier = None
    if level != "high":
        outlier = max(values, key=lambda name: abs(values[name] - mid))
    return {
        "min": round(ordered[0], digits),
        "median": round(mid, digits),
        "max": round(ordered[-1], digits),
        "spread": round(spread, digits),
        "agreement": level,
        "outlier": outlier,
        "models": len(values),
    }


def summarize_spread(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize model agreement per local day.

    Returns ``{"days": [...], "models_used": [...], "models_failed": {name: reason},
    "models_skipped": [...]}``. Days covered by fewer than two models are omitted
    because there is nothing to compare.
    """
    per_model: dict[str, dict[str, dict[str, float]]] = {}
    failed: dict[str, str] = {}
    skipped: list[str] = []
    for result in results:
        name = result.get("name", "?")
        if result.get("skipped"):
            skipped.append(name)
            continue
        hourly = (result.get("data") or {}).get("hourly")
        if result.get("error") or not hourly:
            failed[name] = str(result.get("error") or "No data")
            continue
        per_model[name] = _daily_values(hourly)

    all_days = sorted({day for days in per_model.values() for day in days})
    rows = []
    for day in all_days:
        row: dict[str, Any] = {"date": day}
        levels = []
        for key, source, limits, digits in (
            ("high", "high", TEMPERATURE_SPREAD_F, 1),
            ("low", "low", TEMPERATURE_SPREAD_F, 1),
            ("precip", "precip_in", PRECIPITATION_SPREAD_IN, 2),
        ):
            values = {
                name: days[day][source]
                for name, days in per_model.items()
                if day in days and source in days[day]
            }
            if len(values) < 2:
                continue
            row[key] = _summarize(values, limits, digits)
            levels.append(row[key]["agreement"])
        if not levels:
            continue
        row["models"] = max(
            row[key]["models"] for key in ("high", "low", "precip") if key in row
        )
        row["agreement"] = max(levels, key=_LEVEL_ORDER.__getitem__)
        rows.append(row)

    return {
        "days": rows,
        "models_used": sorted(per_model),
        "models_failed": failed,
        "models_skipped": skipped,
    }
