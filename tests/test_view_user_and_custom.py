"""Tests for user and custom-forecast view branches."""

from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.utils import timezone

from weather.models import CustomDailyForecast, DailyForecast, Location
from weather.views import (
    LocationDetailView,
    ModelsView,
    SignUpView,
    _refresh_forecasts_for_location,
)


class SessionDict(dict):
    modified = False


@pytest.mark.django_db
def test_signup_transfers_anonymous_session_locations():
    anonymous = Location.objects.create(name="Anonymous")
    user = User.objects.create_user(username="new-user")
    form = type("Form", (), {"save": lambda _self: user})()
    request = RequestFactory().post("/signup")
    request.session = SessionDict(location_ids=[str(anonymous.id)])
    request.user = User()
    view = SignUpView()
    view.request = request

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("weather.views.login", lambda _request, _user: None)
        response = view.form_valid(form)

    anonymous.refresh_from_db()
    assert response.status_code == 302
    assert anonymous.owner_id == user.id
    assert request.session.modified is True
    assert request.session["location_ids"] == [str(anonymous.id)]


@pytest.mark.django_db
def test_models_view_selects_current_location_and_normals():
    location = Location.objects.create(
        name="Current",
        is_current_location=True,
        avg_high_temp=85,
        avg_low_temp=65,
    )
    request = RequestFactory().get("/models")
    request.session = SessionDict(location_ids=[str(location.id)])
    view = ModelsView()
    view.request = request
    view.args = ()
    view.kwargs = {}

    context = view.get_context_data()

    assert context["default_location_id"] == location.id
    assert context["avg_high_temp"] == 85
    assert context["avg_low_temp"] == 65


@pytest.mark.django_db
def test_location_detail_prefers_authenticated_custom_daily_forecasts():
    user = User.objects.create_user(username="owner")
    location = Location.objects.create(name="Austin", owner=user)
    today = timezone.now().date()
    DailyForecast.objects.create(
        location=location,
        forecast_date=today,
        period_start=timezone.now(),
        period_end=timezone.now() + timedelta(hours=12),
        temperature=70,
        short_forecast="NWS",
        wind_speed=5,
    )
    CustomDailyForecast.objects.create(
        owner=user,
        location=location,
        forecast_date=today,
        period_start=timezone.now(),
        period_end=timezone.now() + timedelta(hours=12),
        temperature=80,
        short_forecast="Custom",
    )
    request = RequestFactory().get("/locations/detail")
    request.user = user
    request.session = SessionDict(location_ids=[str(location.id)])
    view = LocationDetailView()
    view.request = request
    view.object = location
    view.args = ()
    view.kwargs = {}

    context = view.get_context_data()

    assert context["has_custom_daily"] is True
    assert context["daily_forecasts"][0]["day"].short_forecast == "Custom"


@pytest.mark.django_db
def test_refresh_forecasts_stores_nws_periods():
    location = Location.objects.create(
        name="Refresh", latitude=30, longitude=-97
    )
    grid_response = Mock()
    grid_response.json.return_value = {
        "properties": {
            "gridId": "FWD",
            "gridX": 1,
            "gridY": 2,
            "forecast": "https://example.test/forecast",
        }
    }
    forecast_response = Mock()
    forecast_response.json.return_value = {
        "properties": {
            "periods": [
                {
                    "startTime": "2026-08-24T06:00:00Z",
                    "endTime": "2026-08-24T18:00:00Z",
                    "isDaytime": True,
                    "temperature": 78,
                    "windSpeed": "10 to 20 mph",
                    "shortForecast": "Sunny",
                    "detailedForecast": "Clear skies",
                    "probabilityOfPrecipitation": {"value": 10},
                }
            ]
        }
    }
    with patch("requests.get", side_effect=[grid_response, forecast_response]):
        assert _refresh_forecasts_for_location(location) is True

    location.refresh_from_db()
    forecast = DailyForecast.objects.get(location=location)
    assert forecast.temperature == 78
    assert forecast.wind_speed == 15
    assert location.nws_office == "FWD"


@pytest.mark.django_db
def test_forecast_list_includes_current_location_outside_session(client):
    current = Location.objects.create(
        name="Current", is_current_location=True, is_enabled=True
    )
    today = timezone.now().date()
    DailyForecast.objects.create(
        location=current,
        forecast_date=today,
        period_start=timezone.now(),
        period_end=timezone.now() + timedelta(hours=12),
        is_daytime=True,
        temperature=75,
        short_forecast="Clear",
        wind_speed=4,
    )

    response = client.get("/forecasts/")

    assert response.status_code == 200
    assert response.context["forecasts"][0].location_id == current.id


@pytest.mark.django_db
def test_custom_forecast_view_loads_owner_reference_data(client):
    user = User.objects.create_user(username="custom-owner", password="pass")
    location = Location.objects.create(
        name="Owned",
        owner=user,
        latitude=30,
        longitude=-97,
        avg_high_temp=88,
        avg_low_temp=66,
    )
    CustomDailyForecast.objects.create(
        owner=user,
        location=location,
        forecast_date=timezone.now().date(),
        period_start=timezone.now(),
        period_end=timezone.now() + timedelta(hours=12),
        is_daytime=True,
        temperature=82,
        short_forecast="Warm",
    )
    client.force_login(user)
    session = client.session
    session["location_ids"] = [str(location.id)]
    session.save()
    points = Mock(status_code=200)
    points.json.return_value = {
        "properties": {"forecast": "https://example.test/forecast"}
    }
    forecast = Mock(status_code=200)
    forecast.json.return_value = {"properties": {"periods": [{"name": "Today"}]}}

    with patch("requests.get", side_effect=[points, forecast]):
        response = client.get(
            "/forecasts/custom/", {"location_id": str(location.id)}
        )

    assert response.status_code == 200
    assert response.context["climate_normals"] == {"avg_high": 88, "avg_low": 66}
    assert response.context["nws_forecast_periods"] == [{"name": "Today"}]
    assert response.context["custom_forecasts"][0]["afternoon_temp"] == 82
