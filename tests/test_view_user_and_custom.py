"""Tests for user and custom-forecast view branches."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.utils import timezone

from weather.models import CustomDailyForecast, DailyForecast, Location
from weather.views import LocationDetailView, ModelsView, SignUpView


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
