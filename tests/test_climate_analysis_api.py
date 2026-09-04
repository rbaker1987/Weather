"""Tests for persisted historical climate analysis API responses."""

from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from weather.models import (
    HistoricalWeatherObservation,
    Location,
    TeleconnectionObservation,
)


@pytest.mark.django_db
def test_climate_analysis_returns_calendar_day_samples_and_correlation(monkeypatch):
    location = Location.objects.create(name="Austin", latitude=30, longitude=-97)
    client = APIClient()
    session = client.session
    session["location_ids"] = [str(location.id)]
    session.save()
    monkeypatch.setattr(
        "weather.api.climate_analysis_api.ImportClimateDataCommand._import_weather",
        lambda *_args, **_kwargs: 0,
    )
    monkeypatch.setattr(
        "weather.api.climate_analysis_api.ImportClimateDataCommand.import_noaa_calendar_day",
        lambda *_args, **_kwargs: 0,
    )
    monkeypatch.setattr(
        "weather.api.climate_analysis_api.ClimateAnalysisAPIView.first_year", 2019,
    )

    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2023, 1, 2)

    monkeypatch.setattr("weather.api.climate_analysis_api.date", FakeDate)
    for year in range(2020, 2023):
        observation_date = date(year, 1, 1)
        TeleconnectionObservation.objects.create(
            index_key="nao",
            observation_date=observation_date,
            value=float(year - 2019),
            source_url="https://example.com/nao",
        )
        for offset in range(-3, 4):
            HistoricalWeatherObservation.objects.create(
                location=location,
                observation_date=observation_date + timedelta(days=offset),
                source_kind="ncei_station",
                mean_temperature=float((year - 2019) * 10 + offset),
            )

    response = client.get(
        "/api/climate-analysis/",
        {"location_id": str(location.id), "month": "1", "day": "1", "index": "nao"},
    )

    assert response.status_code == 200
    assert len(response.data["weather"]) == 3
    assert response.data["calendar_day"] == "01-01"
    assert response.data["year_count"] == 3
    assert response.data["sample_count"] == 3
    correlation = next(
        item
        for item in response.data["correlations"]
        if item["index"] == "nao" and item["weather_variable"] == "mean_temperature"
    )
    assert correlation == {"index": "nao", "weather_variable": "mean_temperature", "value": 1.0, "sample_count": 3}


@pytest.mark.django_db
def test_climate_analysis_rejects_location_not_in_session():
    location = Location.objects.create(name="Hidden")

    response = APIClient().get(
        "/api/climate-analysis/",
        {"location_id": str(location.id), "month": "1", "day": "1"},
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_location_detail_registers_anonymous_location_for_climate_analysis():
    location = Location.objects.create(name="Austin", latitude=30, longitude=-97)
    client = APIClient()

    detail_response = client.get(f"/locations/{location.id}/")

    assert detail_response.status_code == 200
    assert str(location.id) in client.session["location_ids"]


@pytest.mark.django_db
def test_climate_analysis_rejects_large_sync_weather_backfill(monkeypatch, settings):
    location = Location.objects.create(name="Austin")
    client = APIClient()
    session = client.session
    session["location_ids"] = [str(location.id)]
    session.save()
    settings.CELERY_ENABLED = False

    def fail_if_called(*args, **kwargs):
        raise AssertionError("synchronous weather import should not run for large backfill")

    monkeypatch.setattr(
        "weather.api.climate_analysis_api.ImportClimateDataCommand._import_weather",
        fail_if_called,
    )

    response = client.get(
        "/api/climate-analysis/",
        {"location_id": str(location.id), "month": "1", "day": "1", "index": "nao"},
    )

    assert response.status_code == 503
    assert "enable Celery" in response.data["error"]
