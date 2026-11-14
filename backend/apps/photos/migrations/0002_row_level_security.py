from django.db import migrations

from apps.core.tenancy import enable_rls


class Migration(migrations.Migration):
    dependencies = [("photos", "0001_initial")]

    operations = [enable_rls("photos_uploadsession"), enable_rls("photos_photo")]
