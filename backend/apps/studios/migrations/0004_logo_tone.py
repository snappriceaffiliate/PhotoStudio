from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("studios", "0003_profile")]

    operations = [
        migrations.AddField(
            model_name="studio",
            name="logo_tone",
            field=models.CharField(blank=True, max_length=5),
        ),
    ]
