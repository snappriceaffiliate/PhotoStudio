from datetime import timedelta

from django.conf import settings
from django.db import migrations
from django.utils import timezone

from apps.core.tenancy import enable_rls

# Starting prices from the project plan; placeholders until confirmed. Edit in the admin.
PLANS = [
    ("starter", "Starter", 99900, 5, 3000, 1, 1),
    ("studio", "Studio", 249900, 20, 8000, 3, 2),
    ("pro", "Pro", 599900, None, 15000, 10, 3),
]


def create_plans_and_trials(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for code, name, price, events, photos, staff, order in PLANS:
        Plan.objects.get_or_create(
            code=code,
            defaults=dict(
                name=name, price_paise=price, max_active_events=events,
                max_photos_per_event=photos, max_staff=staff, sort_order=order,
            ),
        )
    # Studios created before billing existed start a fresh trial. Runs as the table
    # owner during migration, so turn row-level security off for this statement only.
    schema_editor.execute("SELECT set_config('app.bypass_rls', 'on', true)")
    Studio = apps.get_model("studios", "Studio")
    Subscription = apps.get_model("billing", "Subscription")
    ends = timezone.now() + timedelta(days=settings.TRIAL_DAYS)
    for studio in Studio.objects.all():
        Subscription.objects.get_or_create(
            studio=studio, defaults={"status": "trialing", "trial_ends_at": ends}
        )


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial"), ("studios", "0001_initial")]

    operations = [
        enable_rls("billing_subscription"),
        migrations.RunPython(create_plans_and_trials, migrations.RunPython.noop),
    ]
