"""Quick debug test to see why update_forecast returns 404."""

import pytest
from decimal import Decimal
from weather.models import Location
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_simple_update_forecast_debug():
    """Debug why update_forecast is returning 404."""
    # Create location
    loc = Location.objects.create(
        name="Test",
        latitude=Decimal("45.5"),
        longitude=Decimal("-122.6")
    )
    
    # Try various URL formats
    client = APIClient()
    
    urls_to_try = [
        f'/api/locations/{loc.pk}/update_forecast/',
        f'/api/locations/{loc.id}/update_forecast/',
        f'/api/locations/{str(loc.pk)}/update_forecast/',
    ]
    
    print(f"\nLocation PK: {loc.pk}")
    print(f"Location ID: {loc.id}")
    print(f"PK type: {type(loc.pk)}")
    
    for url in urls_to_try:
        response = client.post(url)
        print(f"\nURL: {url}")
        print(f"Status: {response.status_code}")
        if response.status_code != 404:
            print(f"Data: {response.data if hasattr(response, 'data') else response.content[:200]}")
    
    assert True  # Just for debugging
