"""Tests for session location middleware."""

import pytest
from django.test import RequestFactory

from weather.middleware import SessionLocationMiddleware


class SessionDict(dict):
    modified = False


@pytest.mark.django_db
def test_middleware_initializes_anonymous_session():
    response = object()
    request = RequestFactory().get("/")
    request.session = SessionDict()
    middleware = SessionLocationMiddleware(lambda _req: response)

    assert middleware(request) is response
    assert request.session["location_ids"] == []
