"""Tests for the standalone web view helpers in weather.web_views."""

import json
from datetime import datetime, time, timedelta

import pytest
from django.test import RequestFactory
from django.utils import timezone

from weather.models import CurrentConditions, DailyForecast, Location, WeatherAlert
from weather.web_views import (
    DashboardView,
    LocationDetailView,
    LocationListView,
    location_forecast_api,
)


def make_forecast(location, forecast_date, temperature=70):
    return DailyForecast.objects.create(
        location=location,
        forecast_date=forecast_date,
        period_start=timezone.make_aware(
            datetime.combine(forecast_date, time(6, 0))
        ),
        period_end=timezone.make_aware(datetime.combine(forecast_date, time(18, 0))),
        is_daytime=True,
        temperature=temperature,
        short_forecast="Sunny",
        wind_speed=5,
    )


@pytest.mark.django_db
def test_dashboard_context_contains_recent_data():
    location = Location.objects.create(name="Dashboard")
    make_forecast(location, timezone.now().date())
    WeatherAlert.objects.create(
        location=location,
        event="Heat Advisory",
        expires=timezone.now() + timedelta(hours=1),
        is_active=True,
    )

    view = DashboardView()
    context = view.get_context_data()

    assert list(context["locations"]) == [location]
    assert context["stats"] == {
        "total_locations": 1,
        "total_forecasts": 1,
        "active_alerts": 1,
    }


@pytest.mark.django_db
def test_location_list_queryset_filters_active_locations():
    active = Location.objects.create(name="Active", is_active=True)
    Location.objects.create(name="Inactive", is_active=False)

    view = LocationListView()

    assert list(view.get_queryset()) == [active]


@pytest.mark.django_db
def test_location_list_context_refreshes_stale_coordinates(monkeypatch):
    location = Location.objects.create(
        name="Stale",
        latitude=40,
        longitude=-75,
    )
    CurrentConditions.objects.create(
        location=location,
        temperature=70,
        condition="Sunny",
        wind_speed=5,
        humidity=50,
        last_observation_time=timezone.now() - timedelta(hours=1),
    )
    view = LocationListView()
    view.request = RequestFactory().get("/locations")
    view.kwargs = {}
    view.object_list = view.get_queryset()
    refreshed = []
    monkeypatch.setattr(
        "weather.web_views.fetch_current_conditions",
        lambda item: refreshed.append(item),
    )

    view.get_context_data(object_list=view.object_list)

    assert refreshed == [location]


@pytest.mark.django_db
def test_location_detail_context_contains_forecasts_and_active_alerts():
    location = Location.objects.create(name="Detail")
    forecast = make_forecast(location, timezone.now().date())
    active_alert = WeatherAlert.objects.create(
        location=location,
        nws_alert_id="DETAIL-ACTIVE",
        event="Warning",
        expires=timezone.now() + timedelta(hours=1),
        is_active=True,
    )
    WeatherAlert.objects.create(
        location=location,
        nws_alert_id="DETAIL-EXPIRED",
        event="Expired",
        expires=timezone.now() - timedelta(hours=1),
        is_active=True,
    )
    view = LocationDetailView()
    view.object = location

    context = view.get_context_data()

    assert list(context["forecasts"]) == [forecast]
    assert list(context["alerts"]) == [active_alert]


@pytest.mark.django_db
def test_location_forecast_api_returns_serialized_forecasts():
    location = Location.objects.create(name="JSON")
    forecast = make_forecast(location, timezone.now().date(), temperature=65)
    request = RequestFactory().get("/forecast", {"days": 1})

    response = location_forecast_api(request, location.id)

    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload["location"]["name"] == "JSON"
    assert payload["forecasts"][0]["id"] == str(forecast.id)
    assert payload["forecasts"][0]["temperature"] == 65
