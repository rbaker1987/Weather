"""Weather app signal handlers."""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Location, ForecastPeriod, DailyForecast, HourlyForecast


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
@receiver(pre_save, sender=DailyForecast)
@receiver(pre_save, sender=HourlyForecast)
def calculate_apparent_temperature(sender, instance, **kwargs):
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
    if instance.temperature_unit == 'C':
        temp_f = (instance.temperature * 9/5) + 32
    
    wind_speed = getattr(instance, 'wind_speed', 0)
    
    # Heat Index calculation for hot conditions (≥80°F)
    # Using simplified Rothfusz regression
    if temp_f >= 80:
        # Calculate relative humidity from dew point if available
        dew_point = getattr(instance, 'dew_point', None)
        humidity_value = getattr(instance, 'humidity', None)
        
        if humidity_value is not None:
            rh = humidity_value
        elif dew_point is not None:
            # Convert dew point to Fahrenheit if needed
            dew_f = dew_point
            if instance.temperature_unit == 'C':
                dew_f = (dew_point * 9/5) + 32
            
            # Calculate relative humidity from temp and dew point
            # Using Magnus-Tetens formula (works best with Celsius)
            import math
            temp_c = (temp_f - 32) * 5/9
            dew_c = (dew_f - 32) * 5/9
            
            # Magnus formula constants
            a = 17.625
            b = 243.04
            
            # Calculate saturation vapor pressure and actual vapor pressure
            alpha_t = (a * temp_c) / (b + temp_c)
            alpha_d = (a * dew_c) / (b + dew_c)
            
            rh = 100 * math.exp(alpha_d - alpha_t)
            rh = max(0, min(100, rh))  # Clamp to 0-100%
        else:
            # Assume 50% relative humidity as default
            rh = 50
        
        # Simplified heat index formula (Rothfusz regression)
        hi = -42.379 + (2.04901523 * temp_f) + (10.14333127 * rh)
        hi += (-0.22475541 * temp_f * rh) + (-0.00683783 * temp_f * temp_f)
        hi += (-0.05481717 * rh * rh) + (0.00122874 * temp_f * temp_f * rh)
        hi += (0.00085282 * temp_f * rh * rh) + (-0.00000199 * temp_f * temp_f * rh * rh)
        
        instance.apparent_temperature = int(round(hi))
        
    # Wind Chill calculation for cold conditions (≤50°F with wind ≥3mph)
    elif temp_f <= 50 and wind_speed >= 3:
        # NWS Wind Chill formula
        wc = 35.74 + 0.6215 * temp_f - 35.75 * (wind_speed ** 0.16)
        wc += 0.4275 * temp_f * (wind_speed ** 0.16)
        
        instance.apparent_temperature = int(round(wc))
        
    # Moderate conditions - apparent temperature equals actual temperature
    else:
        instance.apparent_temperature = instance.temperature