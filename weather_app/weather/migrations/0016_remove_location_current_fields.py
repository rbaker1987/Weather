# Generated migration to remove current_* fields from Location model
# now that CurrentConditions model handles this data

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("weather", "0015_forecastperiod_last_api_update_currentconditions"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="location",
            name="current_temp",
        ),
        migrations.RemoveField(
            model_name="location",
            name="current_apparent_temp",
        ),
        migrations.RemoveField(
            model_name="location",
            name="current_conditions",
        ),
        migrations.RemoveField(
            model_name="location",
            name="current_humidity",
        ),
        migrations.RemoveField(
            model_name="location",
            name="current_wind_speed",
        ),
        migrations.RemoveField(
            model_name="location",
            name="current_wind_direction",
        ),
        migrations.RemoveField(
            model_name="location",
            name="current_wind_gust",
        ),
        migrations.RemoveField(
            model_name="location",
            name="last_observation_time",
        ),
    ]
