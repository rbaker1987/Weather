from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("weather", "0017_custom_daily_forecast"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="customdailyforecast",
            old_name="weather_cust_owner_loca_4c174d_idx",
            new_name="weather_cus_owner_i_091ca9_idx",
        ),
    ]
