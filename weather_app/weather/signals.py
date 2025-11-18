"""Weather app signal handlers."""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Location, ForecastPeriod


@receiver(pre_save, sender=Location)
def validate_location_coordinates(sender, instance, **kwargs):
    """Validate location coordinates before saving."""
    if instance.latitude is not None and instance.longitude is not None:
        # Ensure coordinates are within valid ranges
        if not (-90 <= instance.latitude <= 90):
            raise ValueError(f"Invalid latitude: {instance.latitude}")
        if not (-180 <= instance.longitude <= 180):
            raise ValueError(f"Invalid longitude: {instance.longitude}")


@receiver(post_save, sender=Location)
def location_post_save(sender, instance, created, **kwargs):
    """Handle location post-save operations."""
    if created:
        # Log new location creation
        import logging
        logger = logging.getLogger('weather')
        logger.info(f"New location created: {instance.name}")


@receiver(pre_save, sender=ForecastPeriod)
def calculate_apparent_temperature(sender, instance, **kwargs):
    """Calculate apparent temperature if not provided."""
    if not instance.apparent_temperature and instance.temperature is not None:
        # Simple heat index calculation (you can replace with your existing logic)
        temp_f = instance.temperature
        if instance.temperature_unit == 'C':
            temp_f = (instance.temperature * 9/5) + 32
        
        # Basic apparent temperature calculation
        # Replace this with your existing weather_app logic
        if temp_f >= 80:
            # Simple heat index approximation
            instance.apparent_temperature = int(temp_f + (temp_f - 80) * 0.1)
        elif temp_f <= 50:
            # Simple wind chill approximation  
            wind_speed = getattr(instance, 'wind_speed', 0)
            instance.apparent_temperature = int(temp_f - (wind_speed * 0.2))
        else:
            instance.apparent_temperature = instance.temperature