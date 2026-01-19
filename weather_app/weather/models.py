"""Weather application models.

Django models for weather data, converted from Pydantic models.
Includes geographic support for locations and proper relationships.
"""

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """Abstract base class with created/updated timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Location(TimeStampedModel):
    """Geographic location model with spatial data support."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=200, help_text="Location name (e.g., 'Austin, TX')"
    )
    custom_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Custom display name for this location (optional)",
    )

    # Geographic coordinates
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
        help_text="Latitude in decimal degrees",
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
        help_text="Longitude in decimal degrees",
    )
    zip_code = models.CharField(max_length=10, blank=True, help_text="US ZIP code")

    # NWS-specific data
    nws_office = models.CharField(
        max_length=10, blank=True, help_text="NWS forecast office"
    )
    grid_x = models.IntegerField(
        null=True, blank=True, help_text="NWS grid X coordinate"
    )
    grid_y = models.IntegerField(
        null=True, blank=True, help_text="NWS grid Y coordinate"
    )

    # Status tracking
    is_active = models.BooleanField(default=True)
    is_enabled = models.BooleanField(
        default=True,
        help_text="Whether this location is enabled and visible on other pages",
    )
    last_forecast_update = models.DateTimeField(null=True, blank=True)
    display_order = models.IntegerField(
        default=0, help_text="Order for displaying locations"
    )
    is_current_location = models.BooleanField(
        default=False, help_text="Mark as current/home location"
    )

    # Current conditions (cached)
    current_temp = models.IntegerField(
        null=True, blank=True, help_text="Current temperature"
    )
    current_apparent_temp = models.IntegerField(
        null=True, blank=True, help_text="Current apparent temperature (feels like)"
    )
    current_conditions = models.CharField(
        max_length=200, blank=True, help_text="Current weather conditions"
    )
    current_humidity = models.IntegerField(
        null=True, blank=True, help_text="Current humidity percentage"
    )
    current_wind_speed = models.IntegerField(
        null=True, blank=True, help_text="Current wind speed in mph"
    )
    current_wind_direction = models.CharField(
        max_length=10, blank=True, help_text="Current wind direction"
    )
    current_wind_gust = models.IntegerField(
        null=True, blank=True, help_text="Current wind gust in mph"
    )
    last_observation_time = models.DateTimeField(
        null=True, blank=True, help_text="Last observation timestamp"
    )
    is_favorite = models.BooleanField(
        default=False, help_text="Mark as favorite location"
    )

    # Climate normals (average high/low for this date)
    avg_high_temp = models.FloatField(
        null=True, blank=True, help_text="Average high temperature for this location (°F)"
    )
    avg_low_temp = models.FloatField(
        null=True, blank=True, help_text="Average low temperature for this location (°F)"
    )

    class LocationType(models.TextChoices):
        HOME = "home", "Home"
        WORK = "work", "Work"
        SCHOOL = "school", "School"
        GENERAL = "", "General"

    location_type = models.CharField(
        max_length=20,
        choices=LocationType.choices,
        default=LocationType.GENERAL,
        blank=True,
        help_text="Type/category of location for ordering",
    )

    class Meta:
        verbose_name = "Location"
        verbose_name_plural = "Locations"
        ordering = ["-is_current_location", "display_order", "name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["zip_code"]),
            models.Index(fields=["last_forecast_update"]),
            models.Index(fields=["is_favorite"]),
            models.Index(fields=["is_current_location"]),
        ]

    def __str__(self):
        return self.custom_name if self.custom_name else self.name

    @property
    def display_name(self):
        """Get the display name (custom name if set, otherwise default name)."""
        return self.custom_name if self.custom_name else self.name

    def update_coordinates(self, latitude, longitude):
        """Update coordinates."""
        self.latitude = latitude
        self.longitude = longitude

    def set_as_favorite(self):
        """Set this location as favorite and unset others."""
        Location.objects.filter(is_favorite=True).update(is_favorite=False)
        self.is_favorite = True
        self.save()


class ForecastPeriod(TimeStampedModel):
    """Base forecast period model."""

    class TemperatureUnit(models.TextChoices):
        FAHRENHEIT = "F", "Fahrenheit"
        CELSIUS = "C", "Celsius"

    class WindDirection(models.TextChoices):
        N = "N", "North"
        NE = "NE", "Northeast"
        E = "E", "East"
        SE = "SE", "Southeast"
        S = "S", "South"
        SW = "SW", "Southwest"
        W = "W", "West"
        NW = "NW", "Northwest"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name="forecasts"
    )

    # Time information
    forecast_date = models.DateField(help_text="Date this forecast is for")
    period_start = models.DateTimeField(help_text="Start of forecast period")
    period_end = models.DateTimeField(help_text="End of forecast period")
    is_daytime = models.BooleanField(
        default=True, help_text="Whether this is a daytime forecast"
    )

    # Temperature data
    temperature = models.IntegerField(
        validators=[MinValueValidator(-50), MaxValueValidator(150)],
        help_text="Temperature value",
    )
    temperature_unit = models.CharField(
        max_length=1,
        choices=TemperatureUnit.choices,
        default=TemperatureUnit.FAHRENHEIT,
    )
    apparent_temperature = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-50), MaxValueValidator(150)],
        help_text="Feels-like temperature",
    )

    # Weather conditions
    short_forecast = models.CharField(
        max_length=200, help_text="Brief forecast description"
    )
    detailed_forecast = models.TextField(blank=True, help_text="Detailed forecast text")

    # Wind data
    wind_speed = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(200)],
        help_text="Wind speed in mph",
    )
    wind_direction = models.CharField(
        max_length=2, choices=WindDirection.choices, blank=True
    )
    wind_gust = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(200)],
        help_text="Wind gust speed in mph",
    )

    # Precipitation
    precipitation_probability = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Chance of precipitation as percentage",
    )

    # Data source tracking
    nws_data_url = models.URLField(blank=True, help_text="Source NWS API URL")
    raw_data = models.JSONField(
        null=True, blank=True, help_text="Raw API response data"
    )

    class Meta:
        verbose_name = "Forecast Period"
        verbose_name_plural = "Forecast Periods"
        ordering = ["location", "period_start"]
        unique_together = ["location", "period_start", "period_end"]
        indexes = [
            models.Index(fields=["location", "forecast_date"]),
            models.Index(fields=["period_start"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.location.name} - {self.forecast_date} - {self.short_forecast}"

    def save(self, *args, **kwargs):
        """Save the forecast period."""
        # Don't set apparent_temperature here - let the signal handle it
        super().save(*args, **kwargs)


class HourlyForecast(ForecastPeriod):
    """Hourly weather forecast data."""

    # Additional hourly-specific fields
    humidity = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Relative humidity percentage",
    )
    dew_point = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-50), MaxValueValidator(100)],
        help_text="Dew point temperature",
    )

    class Meta:
        verbose_name = "Hourly Forecast"
        verbose_name_plural = "Hourly Forecasts"
        ordering = ["location", "period_start"]


class DailyForecast(ForecastPeriod):
    """Daily weather forecast data."""

    # Daily-specific fields
    high_temperature = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-50), MaxValueValidator(150)],
        help_text="High temperature for the day",
    )
    low_temperature = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(-50), MaxValueValidator(150)],
        help_text="Low temperature for the day",
    )

    class Meta:
        verbose_name = "Daily Forecast"
        verbose_name_plural = "Daily Forecasts"
        ordering = ["location", "forecast_date"]


class WeatherAlert(TimeStampedModel):
    """Weather alerts and warnings."""

    class Severity(models.TextChoices):
        MINOR = "minor", "Minor"
        MODERATE = "moderate", "Moderate"
        SEVERE = "severe", "Severe"
        EXTREME = "extreme", "Extreme"

    class Urgency(models.TextChoices):
        IMMEDIATE = "immediate", "Immediate"
        EXPECTED = "expected", "Expected"
        FUTURE = "future", "Future"
        PAST = "past", "Past"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name="alerts"
    )

    # Alert identification
    nws_alert_id = models.CharField(
        max_length=100, unique=True, help_text="NWS Alert ID"
    )
    event = models.CharField(max_length=200, help_text="Alert event type")
    headline = models.CharField(max_length=500, help_text="Alert headline")
    description = models.TextField(help_text="Full alert description")

    # Alert metadata
    severity = models.CharField(max_length=20, choices=Severity.choices)
    urgency = models.CharField(max_length=20, choices=Urgency.choices)

    # Timing
    onset = models.DateTimeField(null=True, blank=True, help_text="Alert start time")
    expires = models.DateTimeField(
        null=True, blank=True, help_text="Alert expiration time"
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Source data
    raw_data = models.JSONField(null=True, blank=True, help_text="Raw NWS alert data")

    class Meta:
        verbose_name = "Weather Alert"
        verbose_name_plural = "Weather Alerts"
        ordering = ["-onset", "-created_at"]
        indexes = [
            models.Index(fields=["location", "is_active"]),
            models.Index(fields=["onset"]),
            models.Index(fields=["severity"]),
        ]

    def __str__(self):
        return f"{self.event} - {self.location.name}"

    @property
    def is_expired(self):
        """Check if alert has expired."""
        if not self.expires:
            return False
        return timezone.now() > self.expires


class ForecastRequest(TimeStampedModel):
    """Track forecast requests and API usage."""

    class RequestStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        CACHED = "cached", "Cached"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.CharField(
        max_length=40, blank=True, help_text="Session key for anonymous users"
    )

    # Request details
    locations_requested = models.ManyToManyField(
        Location, related_name="forecast_requests"
    )
    request_type = models.CharField(max_length=20, default="forecast")
    status = models.CharField(
        max_length=20, choices=RequestStatus.choices, default=RequestStatus.PENDING
    )

    # Performance tracking
    response_time_ms = models.IntegerField(
        null=True, blank=True, help_text="API response time in milliseconds"
    )
    cache_hit = models.BooleanField(
        default=False, help_text="Whether this was served from cache"
    )

    # Error tracking
    error_message = models.TextField(
        blank=True, help_text="Error details if request failed"
    )

    class Meta:
        verbose_name = "Forecast Request"
        verbose_name_plural = "Forecast Requests"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session_key", "created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["request_type"]),
        ]

    def __str__(self):
        session_str = self.session_key[:8] if self.session_key else "Unknown"
        return f"Request from session {session_str} at {self.created_at.strftime('%Y-%m-%d %H:%M')}"
