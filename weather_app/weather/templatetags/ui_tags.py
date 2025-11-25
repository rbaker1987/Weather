from django import template

register = template.Library()


@register.filter(name="condition_icon")
def condition_icon(forecast_or_text, period_type="day"):
    """Map a text description to a Font Awesome icon name, adjusted by precipitation probability.

    Can accept either a forecast object or text string.
    If forecast object, will adjust icon based on precipitation probability:
    - High (≥40%): Shows precipitation type (bolt, snowflake, etc.)
    - Medium (20-40%): Shows cloud + precipitation combo
    - Low (<20%): Shows sky condition

    Second parameter (period_type) should be 'day' or 'night' to determine icon choice.
    """
    # Check if this is a forecast object with precipitation_probability
    if hasattr(forecast_or_text, "short_forecast"):
        text = forecast_or_text.short_forecast
        pop = getattr(forecast_or_text, "precipitation_probability", None)
        is_daytime = getattr(forecast_or_text, "is_daytime", True)
    else:
        text = forecast_or_text
        pop = None
        is_daytime = (
            period_type == "day" if isinstance(period_type, str) else bool(period_type)
        )

    if not text:
        return "cloud-moon" if not is_daytime else "cloud-sun"

    cond = str(text).lower()
    is_storm = any(k in cond for k in ("storm", "thunder", "t-storm"))
    is_snow = any(k in cond for k in ("snow", "flurries", "blizzard"))
    is_ice = any(k in cond for k in ("ice", "icy", "freezing", "sleet"))
    # Showers without snow/ice = rain showers; snow showers = snow
    is_rain = any(k in cond for k in ("rain", "shower", "drizzle")) and not is_snow and not is_ice
    is_mixed = is_rain and is_snow  # Mixed precipitation

    # If we have precipitation probability, adjust icon based on it
    if pop is not None:
        try:
            pop_val = int(pop)

            if pop_val >= 45:
                # High chance: show precipitation type
                if is_storm:
                    return "bolt"
                if is_mixed:
                    return "cloud-meatball"  # Wintry mix icon for mixed precip
                if is_snow:
                    return "snowflake"
                if is_ice:
                    return "icicles"
                if is_rain:
                    return "tint"  # Just raindrop for high chance rain
                # Fall through to default for non-precipitation conditions
            elif pop_val >= 15:
                # Medium chance: show cloud + precipitation
                if is_storm:
                    return "cloud-bolt"
                if is_mixed:
                    return "cloud-meatball"  # Wintry mix for mixed precip
                if is_snow:
                    return "cloud-snow"
                if is_ice:
                    return "cloud-meatball"
                if is_rain:
                    return "cloud-rain"
                # Fall through to default for non-precipitation conditions
            else:
                # Low chance: show just sky type
                if "partly" in cond:
                    return "cloud-sun" if is_daytime else "cloud-moon"
                if any(k in cond for k in ("sunny", "clear")):
                    return "sun" if is_daytime else "moon"
                if any(k in cond for k in ("cloud", "overcast")):
                    return "cloud"
                # Fall through to default for other conditions
        except (TypeError, ValueError):
            pass

    # Default behavior (no PoP or couldn't parse it)
    if is_storm:
        return "bolt"
    if is_ice:
        return "icicles"
    if is_snow:
        return "snowflake"
    if any(k in cond for k in ("fog", "mist", "haze")):
        return "smog"
    if any(k in cond for k in ("rain", "shower", "drizzle")):
        return "cloud-rain"
    if "wind" in cond:
        return "wind"
    if "partly" in cond:
        return "cloud-sun" if is_daytime else "cloud-moon"
    if any(k in cond for k in ("sunny", "clear", "fair")):
        return "sun" if is_daytime else "moon"
    if any(k in cond for k in ("cloud", "overcast")):
        return "cloud"
    return "cloud-sun" if is_daytime else "cloud-moon"


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
    if hasattr(forecast_or_temp, "temperature") and hasattr(
        forecast_or_temp, "apparent_temperature"
    ):
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


@register.filter(name="pop_icon")
def pop_icon(forecast_or_pop, condition_text=None):
    """Return icon for precipitation probability display.

    Always returns 'tint' (water droplet) icon for PoP percentage display.

    Usage:
        {{ period|pop_icon }}
    """
    return "tint"


@register.filter(name="is_mixed_precip")
def is_mixed_precip(forecast_or_text):
    """Return True if forecast text indicates mixed rain and snow.

    Detects presence of any rain keywords AND any snow keywords.
    Can accept either a forecast object or text string.
    Safe for None input.
    """
    if hasattr(forecast_or_text, "short_forecast"):
        text = forecast_or_text.short_forecast
    else:
        text = forecast_or_text

    if not text:
        return False
    cond = str(text).lower()
    snow = any(k in cond for k in ("snow", "flurries", "blizzard"))
    ice = any(k in cond for k in ("ice", "icy", "freezing", "sleet"))
    # Showers without snow/ice = rain showers; snow showers = snow only
    rain = any(k in cond for k in ("rain", "shower", "drizzle")) and not snow and not ice
    return rain and snow


@register.filter(name="is_snow_precip")
def is_snow_precip(forecast_or_text):
    """Return True if forecast text indicates any snow related precipitation without rain keywords.

    Can accept either a forecast object or text string.
    Used for chance snow layout (cloud with flakes beneath).
    """
    if hasattr(forecast_or_text, "short_forecast"):
        text = forecast_or_text.short_forecast
    else:
        text = forecast_or_text

    if not text:
        return False
    cond = str(text).lower()
    # Check for snow keywords - 'snow' will match 'light snow', 'heavy snow', etc.
    snow = any(k in cond for k in ("snow", "flurries", "blizzard"))
    ice = any(k in cond for k in ("ice", "icy", "freezing", "sleet"))
    # Showers without snow/ice = rain showers; snow showers = snow only
    rain = any(k in cond for k in ("rain", "shower", "drizzle")) and not snow and not ice
    return snow and not rain


@register.filter(name="round_pop")
def round_pop(value):
    """Round precipitation probability to nearest 10%.

    Usage:
        {{ period.precipitation_probability|round_pop }}
    """
    if value is None:
        return None
    try:
        pop_val = int(value)
        return round(pop_val / 10) * 10
    except (TypeError, ValueError):
        return value


@register.filter(name="needs_chance_layout")
def needs_chance_layout(forecast_obj):
    """Check if this forecast should use the chance layout (cloud with icons below).

    Returns 'mixed' for mixed precip, 'snow' for snow-only 20-49%, or empty string.
    """
    if not hasattr(forecast_obj, "short_forecast"):
        return ""

    text = forecast_obj.short_forecast
    pop = getattr(forecast_obj, "precipitation_probability", None)

    if not text:
        return ""

    # Handle None or empty PoP - but still check for mixed
    cond = str(text).lower()
    is_snow = any(k in cond for k in ("snow", "flurries", "blizzard"))
    is_ice = any(k in cond for k in ("ice", "icy", "freezing", "sleet"))
    # Showers without snow/ice = rain showers; snow showers = snow only
    is_rain = any(k in cond for k in ("rain", "shower", "drizzle")) and not is_snow and not is_ice
    is_storm = any(k in cond for k in ("storm", "thunder", "t-storm"))

    # Mixed precipitation - only if both rain AND snow (snow showers = snow only)
    if is_rain and is_snow:
        return "mixed"

    # For snow-only or storm, we need a valid PoP
    if pop is None:
        return ""

    try:
        pop_val = int(pop)
    except (TypeError, ValueError):
        return ""

    # Storm with 15-44% PoP (chance)
    if is_storm and pop_val >= 15 and pop_val <= 44:
        return "storm"

    # Snow-only with 15-44% PoP (chance - rounds to 20-40%)
    if is_snow and not is_rain and pop_val >= 15 and pop_val <= 44:
        return "snow"

    return ""
