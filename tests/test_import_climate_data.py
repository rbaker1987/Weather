"""Tests for the historical climate data importer."""

from pathlib import Path

import pytest
from django.core.management import call_command

from weather.models import HistoricalWeatherObservation, Location, TeleconnectionObservation


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
        lambda *args, **kwargs: MockResponse(),
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
