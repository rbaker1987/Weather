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
def test_climate_analysis_returns_session_location_data_and_correlation():
    location = Location.objects.create(name="Austin")
    client = APIClient()
    session = client.session
    session["location_ids"] = [str(location.id)]
    session.save()
    start_date = date(2020, 1, 1)
    for day_offset in range(3):
        observation_date = start_date + timedelta(days=day_offset)
        TeleconnectionObservation.objects.create(
            index_key="nao",
            observation_date=observation_date,
            value=float(day_offset + 1),
            source_url="https://example.com/nao",
        )
        HistoricalWeatherObservation.objects.create(
            location=location,
            observation_date=observation_date,
            source_kind="ncei_station",
            mean_temperature=float((day_offset + 1) * 10),
        )

    response = client.get(
        "/api/climate-analysis/",
        {"location_id": str(location.id), "start_date": "2020-01-01", "end_date": "2020-01-03", "index": "nao"},
    )

    assert response.status_code == 200
    assert len(response.data["weather"]) == 3
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
        {"location_id": str(location.id), "start_date": "2020-01-01", "end_date": "2020-01-03"},
    )

    assert response.status_code == 404
