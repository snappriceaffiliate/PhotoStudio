from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("clients", "0003_client_phone")]

    operations = [
        migrations.AddField(
            model_name="clientaccess",
            name="reminder_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="clientaccess",
            name="last_reminded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="clientaccess",
            name="reminder_emailed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
