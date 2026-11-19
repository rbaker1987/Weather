"""Tests for Django web interface views."""

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestHomeView:
    def test_home_offers_search_and_my_location_without_session(self, client):
        resp = client.get(reverse("weather:home"))

        assert resp.status_code == 200
        assert resp.context["page_title"] == "Weather"
        content = resp.content.decode()
        assert 'id="placeSearch"' in content
        assert 'id="placeUseMyLocation"' in content
        assert reverse("weather:geocode") in content
        assert "location_ids" not in client.session
