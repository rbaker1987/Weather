"""Tests for Django view helper and location viewset branches."""

from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from rest_framework.test import APIRequestFactory

from weather.models import Location
from weather.views import LocationViewSet, fetch_current_conditions


class SessionDict(dict):
    modified = False


@pytest.mark.django_db
def test_fetch_current_conditions_skips_missing_coordinates():
    location = Location.objects.create(name="Unknown")

    assert fetch_current_conditions(location) is False


@pytest.mark.django_db
def test_fetch_current_conditions_returns_service_result():
    location = Location.objects.create(name="Known", latitude=30, longitude=-97)

    with patch(
        "weather.services.CurrentConditionsService.fetch_and_cache_current_conditions",
        return_value=object(),
    ):
        assert fetch_current_conditions(location) is True


@pytest.mark.django_db
def test_fetch_current_conditions_handles_service_error():
    location = Location.objects.create(name="Broken", latitude=30, longitude=-97)

    with patch(
        "weather.services.CurrentConditionsService.fetch_and_cache_current_conditions",
        side_effect=RuntimeError("offline"),
    ):
        assert fetch_current_conditions(location) is False


@pytest.mark.django_db
def test_location_viewset_filters_anonymous_locations_by_session():
    visible = Location.objects.create(name="Visible", is_active=True)
    hidden = Location.objects.create(name="Hidden", is_active=True)
    request = APIRequestFactory().get("/api/locations/")
    request.user = Mock(is_authenticated=False)
    request.session = SessionDict(location_ids=[str(visible.id)])

    view = LocationViewSet()
    view.request = request

    assert list(view.get_queryset()) == [visible]
    assert hidden not in view.get_queryset()


@pytest.mark.django_db
def test_location_viewset_perform_create_geocodes_and_queues_tasks():
    request = APIRequestFactory().post("/api/locations/")
    request.user = Mock(is_authenticated=False)
    request.session = SessionDict()
    serializer = Mock()
    location = Location.objects.create(name="Austin", zip_code="78701")
    serializer.save.return_value = location
    geocode_response = Mock()
    geocode_response.json.return_value = [{"lat": "30.2672", "lon": "-97.7431"}]
    geocode_response.raise_for_status.return_value = None

    view = LocationViewSet()
    view.request = request
    with (
        patch("requests.get", return_value=geocode_response),
        patch("weather.tasks.enqueue_current_conditions"),
        patch("weather.tasks.enqueue_forecasts"),
        patch("weather.tasks.enqueue_alerts"),
    ):
        view.perform_create(serializer)

    location.refresh_from_db()
    assert location.latitude == Decimal("30.267200")
    assert location.longitude == Decimal("-97.743100")
    assert str(location.id) in request.session["location_ids"]


def test_location_viewset_perform_create_geocode_failure_does_not_raise():
    request = APIRequestFactory().post("/api/locations/")
    request.user = Mock(is_authenticated=False)
    request.session = SessionDict()
    serializer = Mock()
    serializer.save.return_value = Location(
        name="Offline", latitude=Decimal("30"), longitude=Decimal("-97")
    )

    view = LocationViewSet()
    view.request = request
    with (
        patch("weather.tasks.enqueue_current_conditions", side_effect=RuntimeError),
        patch("weather.views.fetch_current_conditions"),
        patch("weather.views._refresh_forecasts_for_location"),
    ):
        view.perform_create(serializer)
