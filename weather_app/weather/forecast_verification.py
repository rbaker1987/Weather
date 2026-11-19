"""Which model has been right lately? Score past forecasts against station observations.

Nothing is stored. Open-Meteo's previous-runs API returns what each model forecast for
a given hour 1, 3, ... days earlier, and the nearest NWS station reports what actually
happened, so a rolling score can be computed on demand.

Temperature only: station observations are hourly, so a day's high/low can be about
1 F off the true extreme, and precipitation observations are too sparse to score.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .place_service import TTL_GRID, _get_json
from .upstream import get_json

logger = logging.getLogger("weather")

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
# Our model name -> Open-Meteo model id.
MODELS = {
    "GFS": "gfs_seamless",
    "ICON": "icon_seamless",
    "ECMWF": "ecmwf_ifs025",
    "AIFS": "ecmwf_aifs025",
    "GEM": "gem_seamless",
    "NAM": "ncep_nam_conus",
    "HRRR": "ncep_hrrr_conus",
}
LEAD_DAYS = (1, 3)
LOOKBACK_DAYS = 7
MIN_HOURS_PER_DAY = 20
MIN_OBSERVATIONS_PER_DAY = 12
FORECAST_CACHE_SECONDS = 60 * 60
OBSERVATION_CACHE_SECONDS = 60 * 60
OBSERVATION_LIMIT = 500


class VerificationError(Exception):
    """Observations or past forecasts could not be fetched."""


def _celsius_to_fahrenheit(value: float) -> float:
    return value * 9 / 5 + 32


def observed_daily_extremes(
    observations: list[dict[str, Any]], utc_offset_seconds: int
) -> dict[date, tuple[float, float]]:
    """Reduce NWS observation features to {local date: (high F, low F)}."""
    offset = timedelta(seconds=utc_offset_seconds)
    by_day: dict[date, list[float]] = defaultdict(list)
    for feature in observations:
        props = feature.get("properties", {})
        value = (props.get("temperature") or {}).get("value")
        stamp = props.get("timestamp")
        if value is None or not stamp:
            continue
        try:
            moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        by_day[(moment + offset).date()].append(_celsius_to_fahrenheit(float(value)))
    return {
        day: (max(values), min(values))
        for day, values in by_day.items()
        if len(values) >= MIN_OBSERVATIONS_PER_DAY
    }


def forecast_daily_extremes(
    hourly: dict[str, Any], model_id: str, lead: int
) -> dict[date, tuple[float, float]]:
    """Return {date: (high F, low F)} forecast ``lead`` days ahead by one model."""
    times = hourly.get("time") or []
    values = hourly.get(f"temperature_2m_previous_day{lead}_{model_id}") or []
    by_day: dict[date, list[float]] = defaultdict(list)
    for stamp, value in zip(times, values, strict=False):
        if value is None:
            continue
        by_day[date.fromisoformat(str(stamp)[:10])].append(float(value))
    return {
        day: (max(items), min(items))
        for day, items in by_day.items()
        if len(items) >= MIN_HOURS_PER_DAY
    }


def score_forecasts(
    forecast: dict[date, tuple[float, float]],
    observed: dict[date, tuple[float, float]],
    today: date,
) -> dict[str, Any] | None:
    """Mean absolute error and bias of highs/lows over completed, observed days."""
    errors = [
        (forecast[day][0] - observed[day][0], forecast[day][1] - observed[day][1])
        for day in sorted(set(forecast) & set(observed))
        if day < today
    ]
    if not errors:
        return None
    count = len(errors)
    return {
        "days": count,
        "high_mae": round(sum(abs(e[0]) for e in errors) / count, 1),
        "low_mae": round(sum(abs(e[1]) for e in errors) / count, 1),
        "high_bias": round(sum(e[0] for e in errors) / count, 1),
        "low_bias": round(sum(e[1] for e in errors) / count, 1),
    }


def _nearest_station(latitude: float, longitude: float) -> dict[str, str]:
    properties = _get_json(
        f"https://api.weather.gov/points/{latitude},{longitude}", TTL_GRID
    ).get("properties", {})
    stations_url = properties.get("observationStations")
    if not stations_url:
        raise VerificationError("No observation stations near this place")
    features = _get_json(stations_url, TTL_GRID).get("features", [])
    for feature in features:
        props = feature.get("properties", {})
        if props.get("stationIdentifier"):
            return {
                "id": props["stationIdentifier"],
                "name": props.get("name", props["stationIdentifier"]),
            }
    raise VerificationError("No observation stations near this place")


def _fetch_observations(latitude: float, longitude: float, today: date):
    station = _nearest_station(latitude, longitude)
    # Anchor on midnight UTC so the URL (and cache key) is stable for a whole day.
    start = datetime.combine(
        today - timedelta(days=LOOKBACK_DAYS + 1), datetime.min.time(), timezone.utc
    )
    payload = _get_json(
        f"https://api.weather.gov/stations/{station['id']}/observations"
        f"?start={start.strftime('%Y-%m-%dT%H:%M:%SZ')}&limit={OBSERVATION_LIMIT}",
        OBSERVATION_CACHE_SECONDS,
    )
    return station, payload.get("features", [])


def _fetch_previous_runs(latitude: float, longitude: float, models: list[str]):
    variables = ",".join(f"temperature_2m_previous_day{lead}" for lead in LEAD_DAYS)
    return get_json(
        PREVIOUS_RUNS_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "hourly": variables,
            "models": ",".join(MODELS[name] for name in models),
            "past_days": LOOKBACK_DAYS + 1,
            "forecast_days": 1,
            "temperature_unit": "fahrenheit",
            "timezone": "auto",
        },
        timeout=20,
        ttl=FORECAST_CACHE_SECONDS,
    )


def verify_models(
    latitude: float,
    longitude: float,
    models: list[str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Score each model's day-1 and day-3 high/low forecasts for the past week."""
    models = [m for m in (models or MODELS) if m in MODELS]
    today = today or date.today()
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs_future = pool.submit(_fetch_previous_runs, latitude, longitude, models)
        observations_future = pool.submit(
            _fetch_observations, latitude, longitude, today
        )
        try:
            runs = runs_future.result()
            station, features = observations_future.result()
        except VerificationError:
            raise
        except Exception as exc:
            logger.warning("Forecast verification fetch failed: %s", exc)
            raise VerificationError(
                "Could not fetch forecasts or observations"
            ) from exc

    hourly = runs.get("hourly") or {}
    observed = observed_daily_extremes(
        features, int(runs.get("utc_offset_seconds") or 0)
    )
    scored = []
    for name in models:
        scores = {}
        for lead in LEAD_DAYS:
            forecast = forecast_daily_extremes(hourly, MODELS[name], lead)
            result = score_forecasts(forecast, observed, today)
            if result:
                scores[str(lead)] = result
        if scores:
            scored.append({"name": name, "scores": scores})

    best: dict[str, dict[str, str]] = {}
    for lead in LEAD_DAYS:
        entries = [
            (m["name"], m["scores"][str(lead)])
            for m in scored
            if str(lead) in m["scores"]
        ]
        if len(entries) >= 2:
            best[str(lead)] = {
                "high": min(entries, key=lambda e: e[1]["high_mae"])[0],
                "low": min(entries, key=lambda e: e[1]["low_mae"])[0],
            }
    return {
        "station": station,
        "lookback_days": LOOKBACK_DAYS,
        "leads": list(LEAD_DAYS),
        "models": scored,
        "best": best,
    }
