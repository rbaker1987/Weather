from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("weather", "0016_remove_location_current_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomDailyForecast",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "forecast_date",
                    models.DateField(help_text="Date this forecast is for"),
                ),
                (
                    "period_start",
                    models.DateTimeField(help_text="Start of forecast period"),
                ),
                (
                    "period_end",
                    models.DateTimeField(help_text="End of forecast period"),
                ),
                (
                    "is_daytime",
                    models.BooleanField(default=True),
                ),
                (
                    "temperature",
                    models.IntegerField(
                        help_text="Temperature value",
                        validators=[
                            django.core.validators.MinValueValidator(-50),
                            django.core.validators.MaxValueValidator(150),
                        ],
                    ),
                ),
                (
                    "temperature_unit",
                    models.CharField(
                        choices=[("F", "Fahrenheit"), ("C", "Celsius")],
                        default="F",
                        max_length=1,
                    ),
                ),
                (
                    "apparent_temperature",
                    models.IntegerField(
                        blank=True,
                        help_text="Feels-like temperature",
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(-50),
                            django.core.validators.MaxValueValidator(150),
                        ],
                    ),
                ),
                (
                    "short_forecast",
                    models.CharField(max_length=200),
                ),
                (
                    "detailed_forecast",
                    models.TextField(blank=True),
                ),
                (
                    "wind_speed",
                    models.IntegerField(
                        default=0,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(200),
                        ],
                    ),
                ),
                (
                    "wind_direction",
                    models.CharField(blank=True, max_length=2),
                ),
                (
                    "wind_gust",
                    models.IntegerField(
                        blank=True,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(200),
                        ],
                    ),
                ),
                (
                    "precipitation_probability",
                    models.IntegerField(
                        blank=True,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(100),
                        ],
                    ),
                ),
                (
                    "location",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="custom_daily_forecasts",
                        to="weather.location",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="custom_daily_forecasts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Custom Daily Forecast",
                "verbose_name_plural": "Custom Daily Forecasts",
                "ordering": ["location", "forecast_date", "-is_daytime"],
                "unique_together": {("owner", "location", "forecast_date", "is_daytime")},
                "indexes": [
                    models.Index(fields=["owner", "location", "forecast_date"], name="weather_cust_owner_loca_4c174d_idx"),
                ],
            },
        ),
    ]
