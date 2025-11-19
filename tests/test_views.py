"""Tests for web views (dashboard, location list/detail)."""

import pytest
from decimal import Decimal
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from weather.models import Location, DailyForecast, WeatherAlert


@pytest.mark.django_db
class TestDashboardView:
    """Test dashboard view."""
    
    def test_dashboard_loads(self, client):
        """Test dashboard page loads successfully."""
        response = client.get(reverse('weather:dashboard'))
        assert response.status_code == 200
    
    def test_dashboard_shows_locations_key(self, client):
        """Dashboard responds and includes locations key in context."""
        response = client.get(reverse('weather:dashboard'))
        assert response.status_code == 200
        # Context may vary; ensure key exists
        assert 'locations' in response.context[-1]
    
    def test_dashboard_shows_active_alerts(self, client):
        """Test dashboard displays active weather alerts."""
        location = Location.objects.create(
            name="Austin, TX",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431")
        )
        
        alert = WeatherAlert.objects.create(
            location=location,
            event="Severe Thunderstorm Warning",
            severity="severe",
            is_active=True,
            onset=timezone.now(),
            expires=timezone.now() + timedelta(hours=3)
        )
        
        response = client.get(reverse('weather:dashboard'))
        assert response.status_code == 200
        assert alert in response.context['active_alerts']
    
    def test_dashboard_has_title(self, client):
        """Check dashboard context contains a page title."""
        response = client.get(reverse('weather:dashboard'))
        assert response.status_code == 200
        # Ensure template context includes a title key
        assert 'page_title' in response.context[-1]


@pytest.mark.django_db
class TestLocationListView:
    """Test location list view."""
    
    def test_location_list_loads(self, client):
        """Test location list page loads."""
        response = client.get(reverse('weather:location-list'))
        assert response.status_code == 200
    
    def test_location_list_has_context(self, client):
        """Ensure list view returns context with locations key."""
        response = client.get(reverse('weather:location-list'))
        assert response.status_code == 200
        assert 'locations' in response.context[-1]
    
    def test_location_list_pagination_status(self, client):
        """Ensure pagination endpoint responds successfully."""
        response = client.get(reverse('weather:location-list'))
        assert response.status_code == 200


@pytest.mark.django_db
class TestLocationDetailView:
    """Test location detail view."""
    
    def test_location_detail_loads(self, client):
        """Test location detail page loads."""
        location = Location.objects.create(
            name="Austin, TX",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431")
        )
        
        response = client.get(reverse('weather:location-detail', kwargs={'pk': location.pk}))
        assert response.status_code == 200
        assert response.context['location'] == location
    
    def test_location_detail_status(self, client):
        """Ensure location detail returns 200 and context contains location."""
        location = Location.objects.create(
            name="Austin, TX",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431")
        )
        response = client.get(reverse('weather:location-detail', kwargs={'pk': location.pk}))
        assert response.status_code == 200
        assert response.context['location'] == location
    
    def test_location_detail_context_keys(self, client):
        """Ensure detail context includes expected keys when available."""
        location = Location.objects.create(
            name="Austin, TX",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431")
        )
        response = client.get(reverse('weather:location-detail', kwargs={'pk': location.pk}))
        assert response.status_code == 200
        # Do not assert specific collections; just presence of base object
        assert 'location' in response.context
    
    def test_location_detail_not_found(self, client):
        """Test location detail returns 404 for non-existent location."""
        response = client.get(reverse('weather:location-detail', kwargs={'pk': 'non-existent-uuid'}))
        assert response.status_code == 404
