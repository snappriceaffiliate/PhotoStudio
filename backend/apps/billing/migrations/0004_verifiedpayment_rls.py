from django.db import migrations

from apps.core.tenancy import enable_rls


class Migration(migrations.Migration):
    dependencies = [("billing", "0003_verified_payments")]

    operations = [enable_rls("billing_verifiedpayment")]
