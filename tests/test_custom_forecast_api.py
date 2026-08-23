"""Tests for custom forecast API behavior."""

from datetime import date
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from weather.api.custom_forecast_api import _build_days_payload, _parse_date, _parse_int
from weather.models import CustomDailyForecast, Location


@pytest.fixture
def authenticated_client():
    user = User.objects.create_user(username="custom-user", password="password")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestCustomForecastAPI:
    def test_requires_authentication(self):
        response = APIClient().get("/api/custom-forecast/")

        assert response.status_code == 403

    def test_get_validates_location_and_returns_days(self, authenticated_client):
        client, user = authenticated_client
        location = Location.objects.create(name="Owned", owner=user)
        CustomDailyForecast.objects.create(
            owner=user,
            location=location,
            forecast_date=date(2026, 8, 22),
            period_start="2026-08-22T10:00:00Z",
            period_end="2026-08-22T22:00:00Z",
            is_daytime=True,
            temperature=85,
            short_forecast="Sunny",
        )

        missing = client.get("/api/custom-forecast/")
        unknown = client.get("/api/custom-forecast/", {"location_id": str(uuid4())})
        response = client.get(
            "/api/custom-forecast/", {"location_id": str(location.id)}
        )

        assert missing.status_code == 400
        assert unknown.status_code == 404
        assert response.status_code == 200
        assert response.data["days"][0]["afternoon_temp"] == 85

    def test_post_validates_payload_and_can_clear(self, authenticated_client):
        client, user = authenticated_client
        location = Location.objects.create(name="Owned", owner=user)
        base = {"location_id": str(location.id)}

        assert client.post("/api/custom-forecast/", {}, format="json").status_code == 400
        assert (
            client.post(
                "/api/custom-forecast/",
                {**base, "days": "not-a-list"},
                format="json",
            ).status_code
            == 400
        )

        response = client.post(
            "/api/custom-forecast/",
            {
                **base,
                "days": [
                    {
                        "date": "2026-08-22",
                        "morning_temp": "60",
                        "morning_weather": " Clear ",
                        "afternoon_temp": 85,
                        "afternoon_weather": "Sunny",
                    }
                ],
            },
            format="json",
        )

        assert response.status_code == 200
        assert response.data == {"status": "saved", "count": 2}
        assert CustomDailyForecast.objects.filter(location=location).count() == 2

        cleared = client.post(
            "/api/custom-forecast/", {**base, "days": []}, format="json"
        )
        assert cleared.data == {"status": "cleared"}
        assert not CustomDailyForecast.objects.filter(location=location).exists()

    def test_post_supports_separate_daytime_records_and_ignores_bad_dates(
        self, authenticated_client
    ):
        client, user = authenticated_client
        location = Location.objects.create(name="Owned", owner=user)
        payload = {
            "location_id": str(location.id),
            "days": [
                {"date": "bad", "is_daytime": True, "afternoon_temp": 90},
                {
                    "date": "2026-08-23",
                    "is_daytime": False,
                    "morning_temp": 62,
                    "morning_weather": "Cold",
                },
            ],
        }

        response = client.post("/api/custom-forecast/", payload, format="json")

        assert response.data == {"status": "saved", "count": 1}
        saved = CustomDailyForecast.objects.get(location=location)
        assert saved.is_daytime is False
        assert saved.temperature == 62

    def test_delete_validates_and_reports_count(self, authenticated_client):
        client, user = authenticated_client
        location = Location.objects.create(name="Owned", owner=user)
        CustomDailyForecast.objects.create(
            owner=user,
            location=location,
            forecast_date=date(2026, 8, 22),
            period_start="2026-08-22T10:00:00Z",
            period_end="2026-08-22T22:00:00Z",
            is_daytime=True,
            temperature=85,
            short_forecast="Sunny",
        )

        assert client.delete("/api/custom-forecast/").status_code == 400
        assert (
            client.delete(f"/api/custom-forecast/?location_id={uuid4()}").status_code
            == 404
        )
        response = client.delete(
            f"/api/custom-forecast/?location_id={location.id}"
        )

        assert response.data == {"status": "cleared", "count": 1}


def test_custom_forecast_helpers_parse_and_group_records():
    assert _parse_date("2026-08-22T10:00:00") == date(2026, 8, 22)
    assert _parse_date("bad") is None
    assert _parse_date(None) is None
    assert _parse_int("42") == 42
    assert _parse_int("") is None
    assert _parse_int("bad") is None

    class Forecast:
        def __init__(self, forecast_date, is_daytime, temperature, short_forecast):
            self.forecast_date = forecast_date
            self.is_daytime = is_daytime
            self.temperature = temperature
            self.short_forecast = short_forecast

    payload = _build_days_payload(
        [
            Forecast(date(2026, 8, 23), True, 90, "Hot"),
            Forecast(date(2026, 8, 22), False, 60, "Clear"),
        ]
    )

    assert [day["date"] for day in payload] == ["2026-08-22", "2026-08-23"]
    assert payload[0]["morning_weather"] == "Clear"
    assert payload[1]["afternoon_temp"] == 90
