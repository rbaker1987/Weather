from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("weather", "0013_location_avg_high_temp_location_avg_low_temp"),
    ]

    operations = [
        migrations.AddField(
            model_name="location",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                help_text="User who owns this location (null for anonymous session)",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="locations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name="location",
            index=models.Index(fields=["owner"], name="weather_loc_owner_idx"),
        ),
    ]
