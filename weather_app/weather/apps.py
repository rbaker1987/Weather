"""Django weather app configuration."""

from django.apps import AppConfig


class WeatherConfig(AppConfig):
    """Weather app configuration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "weather"
    verbose_name = "Weather Forecasting"

    def ready(self):
        """Import signal handlers."""
        import weather.signals  # noqa
