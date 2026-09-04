"""Tests for the historical climate data importer."""

from datetime import date
from pathlib import Path

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError

from weather.management.commands.import_climate_data import Command
from weather.models import (
    HistoricalWeatherObservation,
    Location,
    TeleconnectionObservation,
)


class MockResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "daily": {
                "time": ["2025-09-01", "2025-09-02"],
                "temperature_2m_max": [90, 92],
                "temperature_2m_min": [70, 71],
                "temperature_2m_mean": [80, 81],
                "precipitation_sum": [0.1, 0.0],
                "wind_speed_10m_max": [12, 15],
                "snowfall_sum": [0, 0],
            }
        }


@pytest.mark.django_db
def test_import_climate_data_upserts_weather_and_csv_indices(monkeypatch, tmp_path):
    location = Location.objects.create(
        name="Austin",
        latitude=30.2672,
        longitude=-97.7431,
    )
    monkeypatch.setattr(
        "weather.management.commands.import_climate_data.requests.get",
        lambda *_args, **_kwargs: MockResponse(),
    )
    csv_path = Path(tmp_path) / "indices.csv"
    csv_path.write_text(
        "index,date,value\nnao,2025-09-01,1.2\n", encoding="utf-8"
    )

    call_command(
        "import_climate_data",
        location_id=str(location.id),
        start_date="2025-09-01",
        end_date="2025-09-02",
        teleconnection_file=csv_path,
    )

    assert HistoricalWeatherObservation.objects.filter(location=location).count() == 2
    assert TeleconnectionObservation.objects.get(index_key="nao").value == 1.2

    call_command(
        "import_climate_data",
        location_id=str(location.id),
        start_date="2025-09-01",
        end_date="2025-09-02",
        teleconnection_file=csv_path,
    )
    assert HistoricalWeatherObservation.objects.filter(location=location).count() == 2
    assert TeleconnectionObservation.objects.count() == 1


@pytest.mark.django_db
def test_importer_validates_dates_and_location():
    command = Command()
    with pytest.raises(CommandError):
        command._validate_dates(date(2025, 1, 2), date(2025, 1, 1))
    with pytest.raises(CommandError):
        command._get_location("00000000-0000-0000-0000-000000000000")


def test_importer_rejects_invalid_csv(tmp_path):
    path = Path(tmp_path) / "bad.csv"
    path.write_text("wrong,columns\nvalue,here\n", encoding="utf-8")
    with pytest.raises(CommandError):
        Command()._import_teleconnections(path)


@pytest.mark.django_db
def test_importer_reads_noaa_monthly_rows(monkeypatch):
    class IndexResponse:
        text = "2025 1 2 3 4 5 6 7 8 9 10 11 12\n"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "weather.management.commands.import_climate_data.requests.get",
        lambda *_args, **_kwargs: IndexResponse(),
    )
    count = Command().import_noaa_indices(
        date(2025, 1, 1), date(2025, 1, 3), ["nao"]
    )
    assert count == 3


def test_importer_rejects_missing_csv_and_invalid_index(tmp_path):
    command = Command()
    with pytest.raises(CommandError):
        command._import_teleconnections(Path(tmp_path) / "missing.csv")

    path = Path(tmp_path) / "indices.csv"
    path.write_text("index,date,value\nunknown,2025-01-01,1\n", encoding="utf-8")
    with pytest.raises(CommandError):
        command._import_teleconnections(path)


def test_importer_reports_http_and_json_errors(monkeypatch):
    class FailedResponse:
        def raise_for_status(self):
            raise requests.RequestException("offline")

    monkeypatch.setattr(
        "weather.management.commands.import_climate_data.requests.get",
        lambda *_args, **_kwargs: FailedResponse(),
    )
    with pytest.raises(CommandError):
        Command().import_noaa_indices(date(2025, 1, 1), date(2025, 1, 3), ["nao"])


@pytest.mark.django_db
def test_importer_reads_calendar_day_from_noaa_feeds(monkeypatch):
    class IndexResponse:
        text = "2024 1 2 3 4 5 6 7 8 9 10 11 12\n"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "weather.management.commands.import_climate_data.requests.get",
        lambda *_args, **_kwargs: IndexResponse(),
    )
    count = Command().import_noaa_calendar_day(
        2, 29, [2024], ["nao", "ao", "pna", "oni", "epo"]
    )

    assert count == 5
    assert TeleconnectionObservation.objects.filter(
        observation_date=date(2024, 2, 29)
    ).count() == 5
