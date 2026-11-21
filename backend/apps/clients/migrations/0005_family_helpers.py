import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("clients", "0004_reminders")]

    operations = [
        migrations.AddField(
            model_name="clientaccess",
            name="role",
            field=models.CharField(
                choices=[("main", "Main client"), ("helper", "Family helper")],
                default="main",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="clientaccess",
            name="invited_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="helpers",
                to="clients.clientaccess",
            ),
        ),
    ]
