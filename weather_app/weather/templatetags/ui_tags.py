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
    if "wind" in cond and "cloudy" not in cond:
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
