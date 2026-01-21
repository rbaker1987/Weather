"""Weather app signal handlers."""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import DailyForecast, ForecastPeriod, HourlyForecast, Location
from .utils.apparent_temperature import (
    calculate_apparent_temperature as calc_apparent_temp,
)


@receiver(pre_save, sender=Location)
def validate_location_coordinates(_sender, instance, **_kwargs):
    """Validate location coordinates before saving."""
    if instance.latitude is not None and instance.longitude is not None:
        # Ensure coordinates are within valid ranges
        if not (-90 <= instance.latitude <= 90):
            raise ValueError(f"Invalid latitude: {instance.latitude}")
        if not (-180 <= instance.longitude <= 180):
            raise ValueError(f"Invalid longitude: {instance.longitude}")


@receiver(post_save, sender=Location)
def location_post_save(_sender, instance, created, **_kwargs):
    """Handle location post-save operations."""
    if created:
        # Log new location creation
        import logging

        logger = logging.getLogger("weather")
        logger.info(f"New location created: {instance.name}")


@receiver(pre_save, sender=ForecastPeriod)
@receiver(pre_save, sender=DailyForecast)
@receiver(pre_save, sender=HourlyForecast)
def calculate_apparent_temperature(_sender, instance, **_kwargs):
    """Calculate apparent temperature if not provided by NWS.

    Uses proper heat index formula for hot conditions (≥80°F) and
    wind chill formula for cold conditions (≤50°F with wind).
    If NWS already provided apparent_temperature, it's preserved.
    For heat index, uses humidity from dew point if available.
    """
    # If NWS already provided apparent_temperature, don't override it
    if instance.apparent_temperature is not None:
        return

    if instance.temperature is None:
        return

    # Convert to Fahrenheit if needed
    temp_f = instance.temperature
    if instance.temperature_unit == "C":
        temp_f = (instance.temperature * 9 / 5) + 32

    wind_speed = getattr(instance, "wind_speed", 0)
    dew_point = getattr(instance, "dew_point", None)
    humidity_value = getattr(instance, "humidity", None)

    # Calculate using shared utility
    instance.apparent_temperature = calc_apparent_temp(
        temp_f=temp_f,
        humidity_pct=humidity_value,
        wind_speed_mph=wind_speed,
        dew_point_f=dew_point if instance.temperature_unit == "F" else None,
        dew_point_c=dew_point if instance.temperature_unit == "C" else None,
    )
