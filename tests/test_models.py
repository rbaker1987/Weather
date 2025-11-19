"""Tests for Django weather models."""

import pytest
from decimal import Decimal
from weather.models import Location


@pytest.mark.django_db
class TestLocation:
    """Test the Location model."""

    def test_location_creation(self):
        """Test basic location creation."""
        location = Location.objects.create(
            name="Austin, TX",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431")
        )

        assert location.name == "Austin, TX"
        assert location.latitude == Decimal("30.2672")
        assert location.longitude == Decimal("-97.7431")
        assert location.id is not None
    
    def test_location_custom_name(self):
        """Test location custom name."""
        location = Location.objects.create(
            name="Austin, TX",
            custom_name="Home",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431")
        )

        assert location.display_name == "Home"
    
    def test_location_display_name_fallback(self):
        """Test location display name falls back to name."""
        location = Location.objects.create(
            name="Austin, TX",
            latitude=Decimal("30.2672"),
            longitude=Decimal("-97.7431")
        )

        assert location.display_name == "Austin, TX"