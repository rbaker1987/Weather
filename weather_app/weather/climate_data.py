"""On-demand climate data: NOAA teleconnection indices and Open-Meteo history.

Nothing here touches the database. Upstream files are fetched when needed and kept in
the process-local cache, so a restart simply refetches them.

Weather source: Open-Meteo Archive (daily, F/mph/in, per-location timezone). Indices:
NAO/AO/PNA from CPC CDAS daily files; EPO/WPO from PSL core files standardized per
calendar month (1991-2020); ENSO (internal key ``oni``) is monthly. Monthly indices
are never presented as daily.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

import requests
from django.core.cache import cache

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger("weather")

WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"
# CDAS files run a few days fresher than the .data index files.
_CPC_DAILY = (
    "https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.{}.cdas.{}.19500101_current.csv"
)
_PSL_DAILY = (
    "https://downloads.psl.noaa.gov/Public/map/teleconnections/"
    "{}.core.reanalysis.t10trunc.1950-present.txt"
)
MONTHLY_INDEX_URLS = {
    "nao": "https://psl.noaa.gov/data/correlation/nao.data",
    "ao": "https://psl.noaa.gov/data/correlation/ao.data",
    "pna": "https://psl.noaa.gov/data/correlation/pna.data",
    "oni": "https://psl.noaa.gov/data/correlation/oni.data",
    "epo": "https://psl.noaa.gov/data/correlation/epo.data",
}
# ENSO (oni) is only published monthly; everything else is daily.
DAILY_INDEX_URLS = {
    "nao": _CPC_DAILY.format("nao", "z500"),
    "ao": _CPC_DAILY.format("ao", "z1000"),
    "pna": _CPC_DAILY.format("pna", "z500"),
    "epo": _PSL_DAILY.format("epo"),
    "wpo": _PSL_DAILY.format("wpo"),
}
# PSL publishes raw height differences; scale them to z-scores like the CPC indices.
STANDARDIZED_INDICES = {"epo", "wpo"}
BASELINE_YEARS = range(1991, 2021)
INDEX_KEYS = ("nao", "ao", "pna", "oni", "epo", "wpo")

WEATHER_FIELDS = {
    "temperature_2m_mean": "mean_temperature",
    "precipitation_sum": "precipitation",
    "wind_speed_10m_max": "wind_speed",
    "snowfall_sum": "snowfall",
}

INDEX_CACHE_SECONDS = 6 * 60 * 60
WEATHER_CACHE_SECONDS = 24 * 60 * 60
# Archive data trails real time by a few days.
ARCHIVE_LAG_DAYS = 6


class ClimateDataError(Exception):
    """An upstream climate file or API could not be fetched or parsed."""


@dataclass(frozen=True)
class IndexSeries:
    """One teleconnection index: daily values keyed by date, or monthly by (y, m)."""

    key: str
    cadence: str
    url: str
    values: dict

    def value_on(self, day: date) -> float | None:
        if self.cadence == "daily":
            return self.values.get(day)
        return self.values.get((day.year, day.month))

    def latest(self, on_or_before: date) -> tuple[date, float] | None:
        """Return the most recent (date, value) not after ``on_or_before``."""
        if self.cadence == "daily":
            dates = [d for d in self.values if d <= on_or_before]
            if not dates:
                return None
            newest = max(dates)
            return newest, self.values[newest]
        months = [
            m for m in self.values if m <= (on_or_before.year, on_or_before.month)
        ]
        if not months:
            return None
        year, month = max(months)
        return date(year, month, 1), self.values[(year, month)]


@dataclass(frozen=True)
class WeatherDay:
    """Daily weather for one date (any field may be missing)."""

    mean_temperature: float | None = None
    precipitation: float | None = None
    wind_speed: float | None = None
    snowfall: float | None = None


def parse_daily(text: str) -> dict[date, float]:
    values = {}
    for line in text.splitlines():
        fields = line.replace(",", " ").split()
        if len(fields) != 4:
            continue
        try:
            year, month, day = (int(item) for item in fields[:3])
            value = float(fields[3])
            if value <= -99:
                continue
            values[date(year, month, day)] = value
        except ValueError:
            continue
    return values


def parse_monthly(text: str) -> dict[tuple[int, int], float]:
    values = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 13 or not fields[0].isdigit():
            continue
        year = int(fields[0])
        for month, value_text in enumerate(fields[1:13], start=1):
            try:
                value = float(value_text)
            except ValueError:
                continue
            if value <= -99:
                continue
            values[(year, month)] = value
    return values


def standardize(values: dict[date, float]) -> dict[date, float]:
    """Z-score each value against its calendar month over the baseline period."""
    by_month: dict[int, list[float]] = {}
    for observation_date, value in values.items():
        if observation_date.year in BASELINE_YEARS:
            by_month.setdefault(observation_date.month, []).append(value)
    stats = {}
    for month, items in by_month.items():
        mean = sum(items) / len(items)
        deviation = (sum((item - mean) ** 2 for item in items) / len(items)) ** 0.5
        if deviation:
            stats[month] = (mean, deviation)
    return {
        observation_date: (value - stats[observation_date.month][0])
        / stats[observation_date.month][1]
        for observation_date, value in values.items()
        if observation_date.month in stats
    }


def _get(url: str, *, timeout: int, params: dict | None = None) -> requests.Response:
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ClimateDataError(f"request to {url} failed: {exc}") from exc
    return response


def _download_index(index_key: str) -> IndexSeries:
    daily_url = DAILY_INDEX_URLS.get(index_key)
    if daily_url:
        try:
            values = parse_daily(_get(daily_url, timeout=60).text)
            if index_key in STANDARDIZED_INDICES:
                values = standardize(values)
            if values:
                return IndexSeries(index_key, "daily", daily_url, values)
        except ClimateDataError:
            if index_key not in MONTHLY_INDEX_URLS:
                raise
            logger.warning("Daily %s index unavailable; using monthly", index_key)
    url = MONTHLY_INDEX_URLS.get(index_key)
    if url is None:
        raise ClimateDataError(f"{index_key} has no available data source")
    values = parse_monthly(_get(url, timeout=30).text)
    if not values:
        raise ClimateDataError(f"{index_key} index file had no usable values")
    return IndexSeries(index_key, "monthly", url, values)


def fetch_index_series(index_key: str) -> IndexSeries:
    """Return one index series, cached for a few hours."""
    cache_key = f"climate-index:{index_key}"
    series = cache.get(cache_key)
    if series is None:
        series = _download_index(index_key)
        cache.set(cache_key, series, INDEX_CACHE_SECONDS)
    return series


def fetch_index_series_many(
    index_keys: Iterable[str],
) -> tuple[dict[str, IndexSeries], dict[str, str]]:
    """Fetch several indices in parallel; return (series by key, errors by key)."""
    keys = sorted(set(index_keys))
    series: dict[str, IndexSeries] = {}
    errors: dict[str, str] = {}

    def load(key):
        try:
            return key, fetch_index_series(key), None
        except ClimateDataError as exc:
            logger.warning("Climate index %s failed: %s", key, exc)
            return key, None, str(exc)

    with ThreadPoolExecutor(max_workers=max(1, len(keys))) as pool:
        for key, result, error in pool.map(load, keys):
            if result is not None:
                series[key] = result
            else:
                errors[key] = error or "unavailable"
    return series, errors


def latest_index_values(
    on_or_before: date | None = None,
) -> tuple[list[dict], list[str]]:
    """Return the latest value for each index, plus the keys that failed to load."""
    on_or_before = on_or_before or date.today()
    series, errors = fetch_index_series_many(INDEX_KEYS)
    latest = []
    for key in INDEX_KEYS:
        item = series.get(key)
        found = item.latest(on_or_before) if item else None
        if found is None:
            continue
        latest.append(
            {
                "index": key,
                "date": found[0].isoformat(),
                "value": found[1],
                "cadence": item.cadence,
                "source_url": item.url,
            }
        )
    return latest, sorted(errors)


def fetch_weather_window(
    latitude: float,
    longitude: float,
    month: int,
    day: int,
    first_year: int,
    last_year: int,
    half_window: int = 3,
) -> dict[date, WeatherDay]:
    """Return daily weather for the centered window around month/day in each year.

    One archive request covers the whole range; only the needed window dates are kept
    (and cached) so memory stays small.
    """
    cache_key = (
        f"climate-weather:{latitude:.2f}:{longitude:.2f}:{month}-{day}:"
        f"{first_year}-{last_year}:{half_window}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    start = date(first_year, 1, 1)
    end = min(
        date(last_year + 1, 1, 7), date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
    )
    params = {
        "latitude": round(latitude, 4),
        "longitude": round(longitude, 4),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(WEATHER_FIELDS),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "auto",
    }
    try:
        daily = _get(WEATHER_URL, params=params, timeout=60).json().get("daily") or {}
    except ValueError as exc:
        raise ClimateDataError("historical weather response was not JSON") from exc

    wanted: set[date] = set()
    for year in range(first_year, last_year + 1):
        try:
            center = date(year, month, day)
        except ValueError:
            continue
        wanted.update(
            center + timedelta(days=offset)
            for offset in range(-half_window, half_window + 1)
        )

    times = daily.get("time") or []
    columns = {name: daily.get(name) or [] for name in WEATHER_FIELDS}
    result: dict[date, WeatherDay] = {}
    for position, text in enumerate(times):
        try:
            observed = date.fromisoformat(text)
        except ValueError:
            continue
        if observed not in wanted:
            continue
        result[observed] = WeatherDay(
            **{
                field: _number(columns[name], position)
                for name, field in WEATHER_FIELDS.items()
            }
        )
    if not result:
        raise ClimateDataError("historical weather response had no daily data")
    cache.set(cache_key, result, WEATHER_CACHE_SECONDS)
    return result


def _number(values: list, position: int) -> float | None:
    value = values[position] if position < len(values) else None
    return float(value) if value is not None else None
