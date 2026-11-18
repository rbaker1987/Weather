"""Tests for Django view helper and location viewset branches."""

from unittest.mock import patch

import pytest

from weather.models import Location
from weather.views import LocationViewSet, fetch_current_conditions


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


def test_location_viewset_is_read_only():
    # No list/create/update/delete: rows are not owned by any visitor.
    for name in ("list", "create", "update", "partial_update", "destroy"):
        assert not hasattr(LocationViewSet, name)
    assert hasattr(LocationViewSet, "retrieve")
