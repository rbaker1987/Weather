"""Django REST Framework serializers for weather data."""

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import serializers
from rest_framework.serializers import ModelSerializer, SerializerMethodField

from .models import (
    CurrentConditions,
    DailyForecast,
    ForecastRequest,
    HourlyForecast,
    Location,
    WeatherAlert,
)


class UserSerializer(ModelSerializer):
    """User serializer for API responses."""

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name"]
        read_only_fields = ["id"]


class LocationSerializer(ModelSerializer):
    """Location serializer with geographic data."""

    forecast_count = SerializerMethodField()
    display_name = SerializerMethodField()

    class Meta:
        model = Location
        fields = [
            "id",
            "name",
            "custom_name",
            "display_name",
            "latitude",
            "longitude",
            "zip_code",
            "location_type",
            "nws_office",
            "grid_x",
            "grid_y",
            "is_active",
            "is_favorite",
            "is_current_location",
            "current_temp",
            "current_apparent_temp",
            "current_conditions",
            "current_humidity",
            "current_wind_speed",
            "current_wind_direction",
            "current_wind_gust",
            "last_observation_time",
            "created_at",
            "updated_at",
            "last_forecast_update",
            "forecast_count",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "nws_office",
            "grid_x",
            "grid_y",
        ]

    def get_forecast_count(self, obj):
        """Get count of forecasts for this location."""
        return obj.forecasts.filter(period_start__gte=timezone.now().date()).count()

    def get_display_name(self, obj):
        """Get the display name for the location."""
        return obj.display_name


class CurrentConditionsSerializer(ModelSerializer):
    """Current weather conditions serializer."""

    location_name = serializers.CharField(source="location.name", read_only=True)
    location_id = serializers.CharField(source="location.id", read_only=True)
    is_stale = SerializerMethodField()
    age_minutes = SerializerMethodField()

    class Meta:
        model = CurrentConditions
        fields = [
            "id",
            "location",
            "location_id",
            "location_name",
            "temperature",
            "feels_like_temperature",
            "condition",
            "wind_speed",
            "wind_direction",
            "wind_gust",
            "humidity",
            "precipitation",
            "pressure",
            "visibility",
            "uv_index",
            "last_observation_time",
            "is_stale",
            "age_minutes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "last_observation_time",
        ]

    def get_is_stale(self, obj):
        """Check if data is older than 15 minutes."""
        return obj.is_stale

    def get_age_minutes(self, obj):
        """Get minutes since last update."""
        age = timezone.now() - obj.updated_at
        return int(age.total_seconds() / 60)


class LocationCreateSerializer(serializers.Serializer):
    """Serializer for creating locations from various input formats."""

    name = serializers.CharField(max_length=200, required=False)
    latitude = serializers.FloatField(required=False, min_value=-90, max_value=90)
    longitude = serializers.FloatField(required=False, min_value=-180, max_value=180)
    zip_code = serializers.CharField(max_length=10, required=False)
    address = serializers.CharField(max_length=500, required=False)

    def validate(self, data):
        """Validate that we have enough information to create a location."""
        has_coords = "latitude" in data and "longitude" in data
        has_zip = "zip_code" in data
        has_address = "address" in data
        has_name = "name" in data

        if not any([has_coords, has_zip, has_address, has_name]):
            raise serializers.ValidationError(
                "Must provide either coordinates, zip code, address, or location name"
            )
        return data


class HourlyForecastSerializer(ModelSerializer):
    """Hourly forecast serializer."""

    location_name = serializers.CharField(source="location.name", read_only=True)
    apparent_temperature_display = SerializerMethodField()
    is_stale = SerializerMethodField()

    class Meta:
        model = HourlyForecast
        fields = [
            "id",
            "location",
            "location_name",
            "forecast_date",
            "period_start",
            "period_end",
            "temperature",
            "temperature_unit",
            "apparent_temperature",
            "apparent_temperature_display",
            "short_forecast",
            "detailed_forecast",
            "wind_speed",
            "wind_direction",
            "wind_gust",
            "precipitation_probability",
            "humidity",
            "dew_point",
            "last_api_update",
            "is_stale",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "last_api_update"]

    def get_apparent_temperature_display(self, obj):
        """Get formatted apparent temperature."""
        if obj.apparent_temperature:
            return f"{obj.apparent_temperature}°{obj.temperature_unit}"
        return None

    def get_is_stale(self, obj):
        """Check if forecast is older than 15 minutes."""
        return obj.is_stale


class DailyForecastSerializer(ModelSerializer):
    """Daily forecast serializer."""

    location_name = serializers.CharField(source="location.name", read_only=True)
    temperature_range = SerializerMethodField()
    is_stale = SerializerMethodField()

    class Meta:
        model = DailyForecast
        fields = [
            "id",
            "location",
            "location_name",
            "forecast_date",
            "period_start",
            "period_end",
            "temperature",
            "temperature_unit",
            "high_temperature",
            "low_temperature",
            "temperature_range",
            "apparent_temperature",
            "short_forecast",
            "detailed_forecast",
            "wind_speed",
            "wind_direction",
            "wind_gust",
            "precipitation_probability",
            "last_api_update",
            "is_stale",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "last_api_update"]

    def get_temperature_range(self, obj):
        """Get formatted temperature range."""
        # Handle both DailyForecast (has high/low) and base ForecastPeriod
        high_temp = getattr(obj, "high_temperature", None)
        low_temp = getattr(obj, "low_temperature", None)
        if high_temp and low_temp:
            return f"{low_temp}°{obj.temperature_unit} - {high_temp}°{obj.temperature_unit}"
        return None

    def get_is_stale(self, obj):
        """Check if forecast is older than 15 minutes."""
        return obj.is_stale


class WeatherAlertSerializer(ModelSerializer):
    """Weather alert serializer."""

    location_name = serializers.CharField(source="location.name", read_only=True)
    is_expired = SerializerMethodField()
    time_until_expiry = SerializerMethodField()

    class Meta:
        model = WeatherAlert
        fields = [
            "id",
            "location",
            "location_name",
            "nws_alert_id",
            "event",
            "headline",
            "description",
            "severity",
            "urgency",
            "onset",
            "expires",
            "is_active",
            "is_expired",
            "time_until_expiry",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "is_expired"]

    def get_is_expired(self, obj):
        """Check if alert is expired."""
        return obj.is_expired

    def get_time_until_expiry(self, obj):
        """Get time until alert expires."""
        if obj.expires:
            from django.utils import timezone

            now = timezone.now()
            if obj.expires > now:
                delta = obj.expires - now
                if delta.days > 0:
                    return f"{delta.days} days"
                if delta.seconds > 3600:
                    hours = delta.seconds // 3600
                    return f"{hours} hours"
                minutes = delta.seconds // 60
                return f"{minutes} minutes"
        return None


class ForecastRequestSerializer(ModelSerializer):
    """Forecast request tracking serializer."""

    user_name = serializers.CharField(source="user.username", read_only=True)
    location_names = SerializerMethodField()

    class Meta:
        model = ForecastRequest
        fields = [
            "id",
            "user",
            "user_name",
            "location_names",
            "request_type",
            "status",
            "response_time_ms",
            "cache_hit",
            "error_message",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_location_names(self, obj):
        """Get names of requested locations."""
        return list(obj.locations_requested.values_list("name", flat=True))


class BulkForecastRequestSerializer(serializers.Serializer):
    """Serializer for bulk forecast requests."""

    locations = serializers.ListField(
        child=serializers.CharField(max_length=200),
        min_length=1,
        max_length=20,
        help_text="List of location names, addresses, or ZIP codes",
    )
    forecast_type = serializers.ChoiceField(
        choices=[("hourly", "Hourly"), ("daily", "Daily"), ("both", "Both")],
        default="daily",
    )
    days = serializers.IntegerField(min_value=1, max_value=10, default=5)
    include_alerts = serializers.BooleanField(default=True)

    def validate_locations(self, value):
        """Validate location list."""
        if len(value) > 20:
            raise serializers.ValidationError(
                "Maximum 20 locations allowed per request"
            )
        return value
