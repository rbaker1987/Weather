"""Import historical weather and teleconnection observations."""

from __future__ import annotations

import calendar
import csv
from datetime import date
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError

from weather.models import (
    HistoricalWeatherObservation,
    Location,
    TeleconnectionObservation,
)


class Command(BaseCommand):
    help = "Import historical weather from Open-Meteo and optional teleconnection CSV data"
    weather_url = "https://archive-api.open-meteo.com/v1/archive"
    index_urls = {
        "nao": "https://psl.noaa.gov/data/correlation/nao.data",
        "ao": "https://psl.noaa.gov/data/correlation/ao.data",
        "pna": "https://psl.noaa.gov/data/correlation/pna.data",
        "oni": "https://psl.noaa.gov/data/correlation/oni.data",
        "epo": "https://psl.noaa.gov/data/correlation/epo.data",
    }
    maximum_days = 366

    def add_arguments(self, parser):
        parser.add_argument("--location-id", required=True, type=str)
        parser.add_argument("--start-date", required=True, type=date.fromisoformat)
        parser.add_argument("--end-date", required=True, type=date.fromisoformat)
        parser.add_argument(
            "--teleconnection-file",
            type=Path,
            help="CSV with index,date,value columns; dates may be YYYY-MM-DD",
        )

    def handle(self, *args, **options):
        location = self._get_location(options["location_id"])
        start_date = self._as_date(options["start_date"])
        end_date = self._as_date(options["end_date"])
        self._validate_dates(start_date, end_date)

        weather_count = self._import_weather(location, start_date, end_date)
        if options.get("teleconnection_file"):
            index_count = self._import_teleconnections(options["teleconnection_file"])
        else:
            index_count = self.import_noaa_indices(
                start_date, end_date, self.index_urls.keys()
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
            "timezone": "UTC",
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
                    "high_temperature": self._value(values["temperature_2m_max"], index),
                    "low_temperature": self._value(values["temperature_2m_min"], index),
                    "mean_temperature": self._value(values["temperature_2m_mean"], index),
                    "precipitation": self._value(values["precipitation_sum"], index),
                    "wind_speed": self._value(values["wind_speed_10m_max"], index),
                    "snowfall": self._value(values["snowfall_sum"], index),
                    "source_metadata": {"timezone": "UTC"},
                },
            )
            count += 1
        return count

    def _import_teleconnections(self, path):
        if not path.is_file():
            raise CommandError(f"teleconnection file not found: {path}")
        count = 0
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            required = {"index", "date", "value"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise CommandError("teleconnection CSV must contain index,date,value columns")
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

    def import_noaa_indices(self, start_date, end_date, index_keys):
        """Import CPC monthly indices, expanded across each month's days."""
        count = 0
        for index_key in set(index_keys) & self.index_urls.keys():
            url = self.index_urls[index_key]
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
            except requests.RequestException as exc:
                raise CommandError(f"{index_key} index request failed: {exc}") from exc

            for line in response.text.splitlines():
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
                    month_start = date(year, month, 1)
                    month_end = date(year, month, calendar.monthrange(year, month)[1])
                    range_start = max(start_date, month_start)
                    range_end = min(end_date, month_end)
                    current = range_start
                    while current <= range_end:
                        TeleconnectionObservation.objects.update_or_create(
                            index_key=index_key,
                            observation_date=current,
                            defaults={
                                "value": value,
                                "source_url": url,
                                "source_metadata": {"cadence": "monthly", "month": month},
                            },
                        )
                        count += 1
                        current = current.fromordinal(current.toordinal() + 1)
        return count

    def import_noaa_calendar_day(self, month, day, years, index_keys):
        """Import monthly NOAA values only for one calendar day per year."""
        count = 0
        for index_key in set(index_keys) & self.index_urls.keys():
            url = self.index_urls[index_key]
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
            except requests.RequestException as exc:
                raise CommandError(f"{index_key} index request failed: {exc}") from exc

            values_by_date = {}
            for line in response.text.splitlines():
                fields = line.split()
                if len(fields) < 13 or not fields[0].isdigit():
                    continue
                year = int(fields[0])
                if year not in years:
                    continue
                try:
                    value = float(fields[month])
                except (IndexError, ValueError):
                    continue
                if value <= -99:
                    continue
                try:
                    values_by_date[date(year, month, day)] = value
                except ValueError:
                    continue

            for observation_date, value in values_by_date.items():
                TeleconnectionObservation.objects.update_or_create(
                    index_key=index_key,
                    observation_date=observation_date,
                    defaults={
                        "value": value,
                        "source_url": url,
                        "source_metadata": {"cadence": "monthly", "month": month},
                    },
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
