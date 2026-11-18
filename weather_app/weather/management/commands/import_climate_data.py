"""Import historical weather and teleconnection observations."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError
from timezonefinder import TimezoneFinder

from weather.models import (
    HistoricalWeatherObservation,
    Location,
    TeleconnectionObservation,
)

_TIMEZONE_CACHE = {}


class Command(BaseCommand):
    help = (
        "Import historical weather from Open-Meteo and optional teleconnection CSV data"
    )
    weather_url = "https://archive-api.open-meteo.com/v1/archive"
    index_urls = {
        "nao": "https://psl.noaa.gov/data/correlation/nao.data",
        "ao": "https://psl.noaa.gov/data/correlation/ao.data",
        "pna": "https://psl.noaa.gov/data/correlation/pna.data",
        "oni": "https://psl.noaa.gov/data/correlation/oni.data",
        "epo": "https://psl.noaa.gov/data/correlation/epo.data",
    }
    # CDAS files run a few days fresher than the .ascii index files.
    cpc_daily = "https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.{}.cdas.{}.19500101_current.csv"
    psl_daily = "https://downloads.psl.noaa.gov/Public/map/teleconnections/{}.core.reanalysis.t10trunc.1950-present.txt"
    # ENSO (oni) is only published monthly; everything else is daily.
    daily_index_urls = {
        "nao": cpc_daily.format("nao", "z500"),
        "ao": cpc_daily.format("ao", "z1000"),
        "pna": cpc_daily.format("pna", "z500"),
        "epo": psl_daily.format("epo"),
        "wpo": psl_daily.format("wpo"),
    }
    # PSL publishes raw height differences; scale them to z-scores like the CPC indices.
    standardized_indices = {"epo", "wpo"}
    baseline_years = range(1991, 2021)
    available_index_keys = set(index_urls) | set(daily_index_urls)
    maximum_days = 366

    def add_arguments(self, parser):
        parser.add_argument("--location-id", type=str)
        parser.add_argument("--start-date", required=True, type=date.fromisoformat)
        parser.add_argument("--end-date", required=True, type=date.fromisoformat)
        parser.add_argument(
            "--indices-only",
            action="store_true",
            help="Import teleconnection indices only (no location or weather needed)",
        )
        parser.add_argument(
            "--teleconnection-file",
            type=Path,
            help="CSV with index,date,value columns; dates may be YYYY-MM-DD",
        )

    def handle(self, *args, **options):
        indices_only = options.get("indices_only")
        if not indices_only and not options.get("location_id"):
            raise CommandError("--location-id is required unless --indices-only is set")
        start_date = self._as_date(options["start_date"])
        end_date = self._as_date(options["end_date"])
        self._validate_dates(start_date, end_date)

        weather_count = 0
        if not indices_only:
            location = self._get_location(options["location_id"])
            weather_count = self._import_weather(location, start_date, end_date)
        if options.get("teleconnection_file"):
            index_count = self._import_teleconnections(options["teleconnection_file"])
        else:
            index_count = self.import_noaa_indices(
                start_date, end_date, self.available_index_keys
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {weather_count} weather observations and "
                f"{index_count} teleconnection observations."
            )
        )

    def _get_location(self, location_id):
        try:
            return Location.objects.get(
                id=location_id,
                is_active=True,
                latitude__isnull=False,
                longitude__isnull=False,
            )
        except (Location.DoesNotExist, ValueError) as exc:
            raise CommandError("Location must be active and have coordinates") from exc

    def _validate_dates(self, start_date, end_date):
        days = (end_date - start_date).days + 1
        if start_date > end_date:
            raise CommandError("start date must not be after end date")
        if days > self.maximum_days:
            raise CommandError("date range cannot exceed 366 days")

    def _import_weather(self, location, start_date, end_date):
        timezone_name = self._timezone_for_location(location)
        params = {
            "latitude": float(location.latitude),
            "longitude": float(location.longitude),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": ",".join(
                [
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "temperature_2m_mean",
                    "precipitation_sum",
                    "wind_speed_10m_max",
                    "snowfall_sum",
                ]
            ),
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": timezone_name,
        }
        try:
            response = requests.get(self.weather_url, params=params, timeout=30)
            response.raise_for_status()
            daily = response.json().get("daily") or {}
        except (requests.RequestException, ValueError) as exc:
            raise CommandError(f"historical weather request failed: {exc}") from exc

        dates = daily.get("time") or []
        values = {key: daily.get(key) or [] for key in params["daily"].split(",")}
        count = 0
        for index, date_text in enumerate(dates):
            observation_date = date.fromisoformat(date_text)
            HistoricalWeatherObservation.objects.update_or_create(
                location=location,
                observation_date=observation_date,
                source_kind=HistoricalWeatherObservation.SourceKind.REANALYSIS,
                defaults={
                    "source_identifier": "open-meteo-archive",
                    "source_url": self.weather_url,
                    "high_temperature": self._value(
                        values["temperature_2m_max"], index
                    ),
                    "low_temperature": self._value(values["temperature_2m_min"], index),
                    "mean_temperature": self._value(
                        values["temperature_2m_mean"], index
                    ),
                    "precipitation": self._value(values["precipitation_sum"], index),
                    "wind_speed": self._value(values["wind_speed_10m_max"], index),
                    "snowfall": self._value(values["snowfall_sum"], index),
                    "source_metadata": {"timezone": timezone_name},
                },
            )
            count += 1
        return count

    @staticmethod
    def _timezone_for_location(location):
        latitude = float(location.latitude)
        longitude = float(location.longitude)
        key = (latitude, longitude)
        if key not in _TIMEZONE_CACHE:
            try:
                _TIMEZONE_CACHE[key] = (
                    TimezoneFinder().timezone_at(lat=latitude, lng=longitude) or "UTC"
                )
            except Exception:
                _TIMEZONE_CACHE[key] = "UTC"
        return _TIMEZONE_CACHE[key]

    def _import_teleconnections(self, path):
        if not path.is_file():
            raise CommandError(f"teleconnection file not found: {path}")
        count = 0
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            required = {"index", "date", "value"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise CommandError(
                    "teleconnection CSV must contain index,date,value columns"
                )
            for row in reader:
                index_key = row["index"].strip().lower()
                if index_key not in TeleconnectionObservation.IndexKey.values:
                    raise CommandError(f"unsupported climate index: {index_key}")
                observation_date = date.fromisoformat(row["date"].strip())
                TeleconnectionObservation.objects.update_or_create(
                    index_key=index_key,
                    observation_date=observation_date,
                    defaults={
                        "value": float(row["value"]),
                        "source_url": "https://local.invalid/imported-teleconnection-data",
                        "source_metadata": {
                            "importer": "import_climate_data",
                            "filename": path.name,
                        },
                    },
                )
                count += 1
        return count

    def _fetch_index(self, index_key):
        """Return (cadence, url, values); daily when available, else monthly.

        Daily values are keyed by date; monthly values by (year, month).
        """
        daily_url = self.daily_index_urls.get(index_key)
        if daily_url:
            try:
                response = requests.get(daily_url, timeout=60)
                response.raise_for_status()
                values = self._parse_daily(response.text)
                if index_key in self.standardized_indices:
                    values = self._standardize(values)
                if values:
                    return "daily", daily_url, values
            except requests.RequestException:
                if index_key not in self.index_urls:
                    raise CommandError(f"{index_key} index request failed") from None
        url = self.index_urls.get(index_key)
        if url is None:
            raise CommandError(f"{index_key} has no available data source")
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"{index_key} index request failed: {exc}") from exc
        return "monthly", url, self._parse_monthly(response.text)

    @staticmethod
    def _parse_daily(text):
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

    @classmethod
    def _standardize(cls, values):
        """Z-score each value against its calendar month over the baseline period."""
        by_month = {}
        for observation_date, value in values.items():
            if observation_date.year in cls.baseline_years:
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

    @staticmethod
    def _parse_monthly(text):
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

    def _save_index(self, index_key, observation_date, value, url, cadence):
        TeleconnectionObservation.objects.update_or_create(
            index_key=index_key,
            observation_date=observation_date,
            defaults={
                "value": value,
                "source_url": url,
                "source_metadata": {"cadence": cadence},
            },
        )

    @staticmethod
    def _day_values(cadence, values, observation_date):
        if cadence == "daily":
            return values.get(observation_date)
        return values.get((observation_date.year, observation_date.month))

    def import_noaa_indices(self, start_date, end_date, index_keys):
        """Import daily indices where published; monthly ones span each month's days."""
        count = 0
        for index_key in set(index_keys) & self.available_index_keys:
            cadence, url, values = self._fetch_index(index_key)
            current = start_date
            while current <= end_date:
                value = self._day_values(cadence, values, current)
                if value is not None:
                    self._save_index(index_key, current, value, url, cadence)
                    count += 1
                current += timedelta(days=1)
        return count

    def import_noaa_calendar_day(self, month, day, years, index_keys, half_window=3):
        """Import index values for a calendar day (and its centered window) per year."""
        count = 0
        for index_key in set(index_keys) & self.available_index_keys:
            cadence, url, values = self._fetch_index(index_key)
            for year in years:
                try:
                    center = date(year, month, day)
                except ValueError:
                    continue
                offsets = (
                    range(-half_window, half_window + 1) if cadence == "daily" else [0]
                )
                for offset in offsets:
                    observation_date = center + timedelta(days=offset)
                    value = self._day_values(cadence, values, observation_date)
                    if value is not None:
                        self._save_index(
                            index_key, observation_date, value, url, cadence
                        )
                        count += 1
        return count

    @staticmethod
    def _as_date(value):
        return date.fromisoformat(value) if isinstance(value, str) else value

    @staticmethod
    def _value(values, index):
        value = values[index] if index < len(values) else None
        return float(value) if value is not None else None
