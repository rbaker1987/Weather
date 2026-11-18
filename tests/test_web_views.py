"""Tests for Django web interface views."""

from decimal import Decimal

import pytest
from django.urls import reverse

from weather.models import Location


@pytest.mark.django_db
class TestHomeView:
    def test_home_offers_search_and_my_location_without_session(self, client):
        Location.objects.create(name="Someone Else", latitude=30, longitude=-97)

        resp = client.get(reverse("weather:home"))

        assert resp.status_code == 200
        assert resp.context["page_title"] == "Weather"
        content = resp.content.decode()
        assert 'id="placeSearch"' in content
        assert 'id="placeUseMyLocation"' in content
        assert reverse("weather:geocode") in content
        # Stored locations are never listed on the home page.
        assert "Someone Else" not in content
        assert "location_ids" not in client.session


@pytest.mark.django_db
class TestRefreshForecasts:
    def test_refresh_forecasts_exception_path(self, monkeypatch):
        """Test _refresh_forecasts_for_location handles exception."""
        loc = Location.objects.create(
            name="Fail",
            is_enabled=True,
            latitude=Decimal("1.0"),
            longitude=Decimal("2.0"),
        )
        loc.last_forecast_update = None
        loc.save(update_fields=["last_forecast_update"])

        # Mock requests.get to raise exception
        def bad_get(*args, **kwargs):
            raise Exception("network error")

        monkeypatch.setattr("requests.get", bad_get)
        # Should not crash, just return False and log
        from weather.views import _refresh_forecasts_for_location

        result = _refresh_forecasts_for_location(loc)
        assert result is False


@pytest.mark.django_db
class TestLocationDetailView:
    def test_location_detail_triggers_update_and_alerts(self, client, monkeypatch):
        loc = Location.objects.create(
            name="Needs Update", latitude=Decimal("10.0"), longitude=Decimal("20.0")
        )
        # force update needed
        loc.last_forecast_update = None
        loc.save(update_fields=["last_forecast_update"])

        flags = {"conditions": False, "forecasts": False, "alerts": False}

        monkeypatch.setattr(
            "weather.tasks.enqueue_current_conditions",
            lambda *_: flags.__setitem__("conditions", True),
        )
        monkeypatch.setattr(
            "weather.tasks.enqueue_forecasts",
            lambda *_: flags.__setitem__("forecasts", True),
        )
        monkeypatch.setattr(
            "weather.tasks.enqueue_alerts",
            lambda *_: flags.__setitem__("alerts", True),
        )

        r = client.get(f"/locations/{loc.pk}/")
        assert r.status_code == 200
        assert "daily_forecasts" in r.context
        assert flags["conditions"] is True
        assert flags["forecasts"] is True
        assert flags["alerts"] is True
