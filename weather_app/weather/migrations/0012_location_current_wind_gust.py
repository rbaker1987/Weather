from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('weather', '0011_add_current_apparent_temp'),
    ]

    operations = [
        migrations.AddField(
            model_name='location',
            name='current_wind_gust',
            field=models.IntegerField(blank=True, null=True, help_text='Current wind gust in mph'),
        ),
    ]
