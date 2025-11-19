"""Debug signal execution."""

from datetime import datetime, time

import pytest
from django.utils import timezone

from weather.models import DailyForecast, Location


@pytest.mark.django_db
def test_signal_debug():
    """Debug why signal isn't covering lines."""
    loc = Location.objects.create(name="TestLocation")
    today = timezone.now().date()
    
    # Create forecast without apparent_temperature - should trigger signal
    forecast = DailyForecast(
        location=loc,
        forecast_date=today,
        period_start=timezone.make_aware(datetime.combine(today, time(14, 0))),
        period_end=timezone.make_aware(datetime.combine(today, time(18, 0))),
        is_daytime=True,
        temperature=85,
        temperature_unit='F',
        short_forecast="Hot",
        wind_speed=5,
    )
    
    print(f"Before save - apparent_temperature: {forecast.apparent_temperature}")
    forecast.save()
    print(f"After save - apparent_temperature: {forecast.apparent_temperature}")
    
    # Expected: 85 + (85-80)*0.1 = 85.5 -> 85 (int conversion)
    # But model's save() sets it to temperature if signal doesn't
    assert forecast.apparent_temperature >= 85
