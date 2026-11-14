from django.db import migrations

from apps.core.tenancy import enable_rls


class Migration(migrations.Migration):
    dependencies = [("events", "0001_initial")]

    operations = [enable_rls("events_event")]
