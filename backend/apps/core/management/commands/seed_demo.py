"""Create demo data for local development and staging. Never run in production.

Creates two studios, each with an owner, a staff member and two events, plus a
platform admin. Every account uses the password from DEMO_PASSWORD (default below).
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.models import Plan, Subscription
from apps.core.tenancy import bypass_rls
from apps.events.models import Event
from apps.studios.models import Studio

DEFAULT_PASSWORD = "demo-pass-2026"

STUDIOS = [
    {
        "name": "Lens and Light Studio",
        "slug": "lens-and-light",
        "owner": ("Owner One", "owner@lensandlight.test"),
        "staff": ("Staff One", "staff@lensandlight.test"),
        "events": ["Priya and Arun Wedding", "Meera Baby Shower"],
    },
    {
        "name": "Golden Hour Photography",
        "slug": "golden-hour",
        "owner": ("Owner Two", "owner@goldenhour.test"),
        "staff": ("Staff Two", "staff@goldenhour.test"),
        "events": ["Kavya and Rohan Engagement", "Sharma Family Portraits"],
    },
]


class Command(BaseCommand):
    help = "Create demo studios, users and events (development and staging only)."

    def handle(self, *args, **options):
        if not settings.DEBUG and os.environ.get("ALLOW_DEMO_SEED") != "true":
            raise CommandError(
                "Refusing to seed outside DEBUG. Set ALLOW_DEMO_SEED=true for staging."
            )
        password = os.environ.get("DEMO_PASSWORD", DEFAULT_PASSWORD)
        now = timezone.now()
        with transaction.atomic(), bypass_rls():
            for spec in STUDIOS:
                studio, _ = Studio.objects.get_or_create(
                    slug=spec["slug"], defaults={"name": spec["name"]}
                )
                # Studio 1 is on a paid plan, studio 2 on a fresh trial.
                if not Subscription.objects.filter(studio=studio).exists():
                    if spec["slug"] == "lens-and-light":
                        Subscription.objects.create(
                            studio=studio, status="active", plan=Plan.objects.get(code="studio")
                        )
                    else:
                        Subscription.start_trial(studio)
                for (name, email), role in (
                    (spec["owner"], User.Role.OWNER),
                    (spec["staff"], User.Role.STAFF),
                ):
                    user = User.objects.filter(email=email).first() or User.objects.create_user(
                        email=email, password=password, full_name=name, studio=studio, role=role
                    )
                    user.email_verified_at = user.email_verified_at or now
                    user.save(update_fields=["email_verified_at"])
                for title in spec["events"]:
                    Event.objects.get_or_create(
                        studio=studio, title=title, defaults={"selection_limit": 200}
                    )
            if not User.objects.filter(email="admin@platform.test").exists():
                User.objects.create_superuser(
                    email="admin@platform.test", password=password, full_name="Platform Admin"
                )
        self.stdout.write(self.style.SUCCESS("Demo data ready. Logins are listed in README.md."))
