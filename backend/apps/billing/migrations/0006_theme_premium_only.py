"""The custom theme and logo are a Premium feature: the basic Starter plan does not include it.
Owners can still change this per plan in the admin (Billing > Plans > custom branding)."""

from django.db import migrations


def starter_without_theme(apps, schema_editor):
    apps.get_model("billing", "Plan").objects.filter(code="starter").update(custom_branding=False)


def starter_with_theme(apps, schema_editor):
    apps.get_model("billing", "Plan").objects.filter(code="starter").update(custom_branding=True)


class Migration(migrations.Migration):
    dependencies = [("billing", "0005_branding")]

    operations = [migrations.RunPython(starter_without_theme, starter_with_theme)]
