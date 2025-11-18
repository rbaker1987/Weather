from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('weather', '0005_location_current_conditions_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='location',
            name='location_type',
            field=models.CharField(
                blank=True,
                choices=[('home', 'Home'), ('work', 'Work'), ('school', 'School'), ('', 'General')],
                default='',
                help_text='Type/category of location for ordering',
                max_length=20,
            ),
        ),
    ]
