from django.db import migrations

from apps.core.tenancy import enable_rls


class Migration(migrations.Migration):
    dependencies = [("clients", "0001_initial")]

    operations = [
        enable_rls("clients_clientaccess"),
        enable_rls("clients_selection"),
        enable_rls("clients_submission"),
    ]
