"""On-demand weather for a point, fetched from NWS with no database access.

A "place" is just coordinates plus an optional display name. Nothing here
reads or writes the database, so it works with a disposable cache and carries
the place entirely in the request URL.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from itertools import groupby
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.utils import timezone
from timezonefinder import TimezoneFinder

from .upstream import get_json

logger = logging.getLogger("weather")

NWS_HEADERS = {"User-Agent": "(Weather App, contact@example.com)"}
NWS_TIMEOUT = 10
MAX_DAILY_PERIODS = 14
# Cache lifetimes (seconds): grid lookups never change, the rest follow NWS cadence.
TTL_GRID = 24 * 60 * 60
TTL_FORECAST = 10 * 60
TTL_OBSERVATION = 5 * 60
TTL_ALERTS = 2 * 60
_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_timezone_finder = None


def validate_coordinates(lat, lon):
    """Return (latitude, longitude) floats, or raise ValueError if invalid."""
    try:
        latitude = float(lat)
        longitude = float(lon)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid coordinates") from exc
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Coordinates out of range")
    return latitude, longitude


def parse_wind_speed(wind_speed_str):
    """Extract a numeric wind speed from text like '10 to 15 mph' or '10 mph'."""
    numbers = re.findall(r"\d+", str(wind_speed_str or ""))
    if not numbers:
        return 0
    if len(numbers) > 1:
        return int((int(numbers[0]) + int(numbers[1])) / 2)
    return int(numbers[0])


def _timezone_for(latitude, longitude):
    global _timezone_finder
    try:
        if _timezone_finder is None:
            _timezone_finder = TimezoneFinder()
        name = _timezone_finder.timezone_at(lat=latitude, lng=longitude)
        return ZoneInfo(name) if name else timezone.get_current_timezone()
    except Exception:
        return timezone.get_current_timezone()


def build_place(latitude, longitude, name=None):
    """Create a template-compatible stand-in for a Location (no database row)."""
    label = name or f"{latitude:.2f}, {longitude:.2f}"
    place = SimpleNamespace(
        id=None,
        name=label,
        display_name=label,
        latitude=latitude,
        longitude=longitude,
        zip_code=None,
        nws_office="",
        grid_x=None,
        grid_y=None,
        last_forecast_update=None,
        last_observation_time=None,
        current_temp=None,
        current_conditions="",
        current_humidity=None,
        current_wind_speed=None,
        current_wind_gust=None,
        current_wind_direction="",
        current_apparent_temp=None,
        is_current_location=False,
    )
    place.alerts = SimpleNamespace(filter=lambda **_kwargs: [])
    return place


def _get_json(url, ttl=0):
    return get_json(url, headers=NWS_HEADERS, timeout=NWS_TIMEOUT, ttl=ttl)


def _celsius_to_fahrenheit(value):
    return int(value * 9 / 5 + 32)


def _apply_observation(place, props):
    """Copy a latest-observation payload onto the place's current_* fields."""
    temp_c = (props.get("temperature") or {}).get("value")
    place.current_temp = _celsius_to_fahrenheit(temp_c) if temp_c is not None else None
    place.current_conditions = props.get("textDescription") or "Unknown"

    humidity = (props.get("relativeHumidity") or {}).get("value")
    place.current_humidity = int(humidity) if humidity is not None else None

    wind_kmh = (props.get("windSpeed") or {}).get("value")
    place.current_wind_speed = int(wind_kmh * 0.621371) if wind_kmh is not None else 0
    gust_kmh = (props.get("windGust") or {}).get("value")
    place.current_wind_gust = int(gust_kmh * 0.621371) if gust_kmh is not None else None

    degrees = (props.get("windDirection") or {}).get("value")
    place.current_wind_direction = (
        _COMPASS[int((float(degrees) + 22.5) / 45) % 8] if degrees is not None else ""
    )

    for key in ("heatIndex", "windChill"):
        apparent_c = (props.get(key) or {}).get("value")
        if apparent_c is not None:
            place.current_apparent_temp = _celsius_to_fahrenheit(apparent_c)
            break

    stamp = props.get("timestamp")
    place.last_observation_time = (
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if stamp
        else timezone.now()
    )


def _fetch_current_conditions(place, properties):
    stations_url = properties.get("observationStations")
    if not stations_url:
        return
    stations = _get_json(stations_url, TTL_GRID).get("features", [])
    if not stations:
        return
    station_id = stations[0].get("properties", {}).get("stationIdentifier")
    if not station_id:
        return
    observation = _get_json(
        f"https://api.weather.gov/stations/{station_id}/observations/latest",
        TTL_OBSERVATION,
    )
    _apply_observation(place, observation.get("properties", {}))


def _parse_iso(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _daily_periods(forecast_url, tz):
    periods = (
        _get_json(forecast_url, TTL_FORECAST).get("properties", {}).get("periods", [])
    )
    daily = []
    for period in periods[:MAX_DAILY_PERIODS]:
        start = _parse_iso(period["startTime"]).astimezone(tz)
        end = _parse_iso(period["endTime"]).astimezone(tz)
        is_daytime = period.get("isDaytime", True)
        # A night period that starts after midnight belongs to the previous day.
        if is_daytime or start.hour >= 18:
            forecast_date = start.date()
        else:
            forecast_date = (start - timedelta(days=1)).date()
        daily.append(
            SimpleNamespace(
                forecast_date=forecast_date,
                period_start=start,
                period_end=end,
                is_daytime=is_daytime,
                temperature=period.get("temperature"),
                temperature_unit=period.get("temperatureUnit", "F"),
                wind_speed=parse_wind_speed(period.get("windSpeed", "")),
                wind_direction=period.get("windDirection", ""),
                short_forecast=period.get("shortForecast", ""),
                detailed_forecast=period.get("detailedForecast", ""),
                precipitation_probability=(
                    period.get("probabilityOfPrecipitation") or {}
                ).get("value"),
            )
        )
    return daily


def _group_by_day(daily):
    grouped = []
    for date, periods in groupby(daily, key=lambda f: f.forecast_date):
        periods = list(periods)
        grouped.append(
            {
                "date": date,
                "day": next((p for p in periods if p.is_daytime), None),
                "night": next((p for p in periods if not p.is_daytime), None),
            }
        )
    return grouped


def _fetch_alerts(latitude, longitude):
    features = _get_json(
        f"https://api.weather.gov/alerts/active?point={latitude},{longitude}",
        TTL_ALERTS,
    ).get("features", [])
    alerts = []
    for feature in features:
        props = feature.get("properties", {})
        onset, expires = props.get("onset"), props.get("expires")
        alerts.append(
            SimpleNamespace(
                event=props.get("event", "Unknown"),
                headline=props.get("headline", ""),
                description=props.get("description", ""),
                severity=(props.get("severity") or "unknown").lower(),
                urgency=(props.get("urgency") or "unknown").lower(),
                onset=_parse_iso(onset) if onset else None,
                expires=_parse_iso(expires) if expires else None,
            )
        )
    return alerts


def _safe_alerts(latitude, longitude):
    try:
        return _fetch_alerts(latitude, longitude)
    except Exception as exc:
        logger.warning("Failed to fetch alerts: %s", exc)
        return []


def _safe_current_conditions(place, properties):
    try:
        _fetch_current_conditions(place, properties)
    except Exception as exc:
        logger.warning("Could not fetch current conditions: %s", exc)


def grid_properties(latitude, longitude):
    """NWS grid metadata for a point (cached; raises ``requests`` errors)."""
    return _get_json(
        f"https://api.weather.gov/points/{latitude},{longitude}", TTL_GRID
    ).get("properties", {})


def _iso(value):
    return value.isoformat() if value else None


def fetch_current_panel(latitude, longitude):
    """Current conditions plus NWS grid info for one panel, as plain data."""
    properties = grid_properties(latitude, longitude)
    place = build_place(latitude, longitude)
    _fetch_current_conditions(place, properties)
    return {
        "office": properties.get("gridId", ""),
        "grid_x": properties.get("gridX"),
        "grid_y": properties.get("gridY"),
        "temperature": place.current_temp,
        "apparent_temperature": place.current_apparent_temp,
        "conditions": place.current_conditions,
        "humidity": place.current_humidity,
        "wind_speed": place.current_wind_speed,
        "wind_gust": place.current_wind_gust,
        "wind_direction": place.current_wind_direction,
        "observed_at": _iso(place.last_observation_time),
    }


def _period_data(period):
    return {
        "start": _iso(period.period_start),
        "end": _iso(period.period_end),
        "is_daytime": period.is_daytime,
        "temperature": period.temperature,
        "temperature_unit": period.temperature_unit,
        "wind_speed": period.wind_speed,
        "wind_direction": period.wind_direction,
        "short_forecast": period.short_forecast,
        "detailed_forecast": period.detailed_forecast,
        "precipitation_probability": period.precipitation_probability,
    }


def fetch_forecast_panel(latitude, longitude):
    """Daily forecast for one panel: a list of {date, day, night} dicts."""
    forecast_url = grid_properties(latitude, longitude).get("forecast")
    if not forecast_url:
        return []
    daily = _daily_periods(forecast_url, _timezone_for(latitude, longitude))
    return [
        {
            "date": group["date"].isoformat(),
            "day": _period_data(group["day"]) if group["day"] else None,
            "night": _period_data(group["night"]) if group["night"] else None,
        }
        for group in _group_by_day(daily)
    ]


def fetch_alerts_panel(latitude, longitude):
    """Active NWS alerts for one panel, as plain data."""
    return [
        {
            "event": alert.event,
            "headline": alert.headline,
            "description": alert.description,
            "severity": alert.severity,
            "urgency": alert.urgency,
            "onset": _iso(alert.onset),
            "expires": _iso(alert.expires),
        }
        for alert in _fetch_alerts(latitude, longitude)
    ]


def fetch_place_weather(latitude, longitude, name=None):
    """Fetch current conditions, daily forecast and alerts for a point.

    Returns a dict with ``place``, ``daily_forecasts`` (grouped by day) and
    ``alerts``. Upstream failures are logged and leave the affected parts empty
    so the page can still render. Alerts, observations and the forecast are
    fetched in parallel once the NWS grid point is known.
    """
    place = build_place(latitude, longitude, name)
    daily = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        alerts_future = pool.submit(_safe_alerts, latitude, longitude)
        try:
            properties = grid_properties(latitude, longitude)
            place.nws_office = properties.get("gridId", "")
            place.grid_x = properties.get("gridX")
            place.grid_y = properties.get("gridY")

            conditions_future = pool.submit(_safe_current_conditions, place, properties)
            forecast_url = properties.get("forecast")
            if forecast_url:
                daily = _daily_periods(forecast_url, _timezone_for(latitude, longitude))
            conditions_future.result()
            place.last_forecast_update = timezone.now()
        except Exception as exc:
            logger.warning("Failed to fetch forecast data: %s", exc)
        alerts = alerts_future.result()

    return {
        "place": place,
        "daily_forecasts": _group_by_day(daily),
        "alerts": alerts,
    }
