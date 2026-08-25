"""Tests for session location middleware."""

from unittest.mock import Mock

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory

from weather.middleware import SessionLocationMiddleware
from weather.models import Location


class SessionDict(dict):
    modified = False


@pytest.mark.django_db
def test_middleware_initializes_anonymous_session():
    response = object()
    request = RequestFactory().get("/")
    request.session = SessionDict()
    request.user = Mock(is_authenticated=False)
    middleware = SessionLocationMiddleware(lambda _req: response)

    assert middleware(request) is response
    assert request.session["location_ids"] == []


@pytest.mark.django_db
def test_middleware_syncs_active_owned_locations():
    user = User.objects.create_user(username="owner")
    active = Location.objects.create(name="Active", owner=user, is_active=True)
    Location.objects.create(name="Inactive", owner=user, is_active=False)
    request = RequestFactory().get("/")
    request.session = SessionDict(location_ids=[])
    request.user = user
    middleware = SessionLocationMiddleware(lambda req: req.session)

    result = middleware(request)

    assert result["location_ids"] == [str(active.id)]
    assert request.session.modified is True


@pytest.mark.django_db
def test_middleware_keeps_matching_authenticated_session():
    user = User.objects.create_user(username="owner")
    location = Location.objects.create(name="Active", owner=user)
    request = RequestFactory().get("/")
    request.session = SessionDict(location_ids=[str(location.id)])
    request.user = user
    middleware = SessionLocationMiddleware(lambda req: req.session)

    middleware(request)

    assert request.session.modified is False
