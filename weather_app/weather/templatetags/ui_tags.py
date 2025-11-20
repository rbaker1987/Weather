from django import template

register = template.Library()


@register.filter(name="condition_icon")
def condition_icon(text):
    """Map a text description to a Font Awesome icon name.

    Expects a string; handles None safely by returning a default icon.
    """
    if not text:
        return "cloud-sun"
    cond = str(text).lower()
    if any(k in cond for k in ("storm", "thunder", "t-storm")):
        return "bolt"
    if any(k in cond for k in ("ice", "icy", "freezing", "sleet")):
        return "icicles"
    if any(k in cond for k in ("snow", "flurries", "blizzard")):
        return "snowflake"
    if any(k in cond for k in ("fog", "mist", "haze")):
        return "smog"
    if any(k in cond for k in ("rain", "shower", "drizzle")):
        return "cloud-rain"
    if "wind" in cond:
        return "wind"
    if "partly" in cond:
        return "cloud-sun"
    if any(k in cond for k in ("sunny", "clear", "fair")):
        return "sun"
    if any(k in cond for k in ("cloud", "overcast")):
        return "cloud"
    return "cloud-sun"


@register.filter(name="temp_bg_class")
def temp_bg_class(value):
    """Return a CSS class for temperature background if value is valid."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return ""
    return f"temp-bg-{v}"


@register.filter(name="should_show_feels_like")
def should_show_feels_like(forecast_or_temp, apparent_temp=None):
    """Determine if apparent temperature should be displayed.
    
    Returns True if apparent temperature differs significantly from actual temperature.
    Can be called with a forecast object or with actual_temp and apparent_temp separately.
    
    Usage:
        {% if forecast|should_show_feels_like %}
        or
        {% if actual_temp|should_show_feels_like:apparent_temp %}
    """
    # If called with a forecast object
    if hasattr(forecast_or_temp, 'temperature') and hasattr(forecast_or_temp, 'apparent_temperature'):
        actual = forecast_or_temp.temperature
        apparent = forecast_or_temp.apparent_temperature
    # If called with separate values
    else:
        actual = forecast_or_temp
        apparent = apparent_temp
    
    # Check if both values are valid
    if actual is None or apparent is None:
        return False
    
    try:
        actual_val = int(actual)
        apparent_val = int(apparent)
    except (TypeError, ValueError):
        return False
    
    # Show if difference is 3 degrees or more
    return abs(actual_val - apparent_val) >= 3
