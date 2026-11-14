"""Create a large event for load testing (development and staging only).

    python manage.py seed_load_test --photos 3000

Photos get fake storage keys: the load test measures the API, not image delivery.
Logins: studio owner loadowner@loadtest.test, client username loadclient, both with
the password in LOAD_TEST_PASSWORD (default "load-test-pass-2026").
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.models import Plan, Subscription
from apps.clients.models import ClientAccess, Selection
from apps.core.tenancy import bypass_rls
from apps.events.models import Event
from apps.photos.models import Photo
from apps.studios.models import Studio


class Command(BaseCommand):
    help = "Create a load-test studio with one big shared event."

    def add_arguments(self, parser):
        parser.add_argument("--photos", type=int, default=3000)

    def handle(self, *args, photos, **options):
        if not settings.DEBUG and os.environ.get("ALLOW_DEMO_SEED") != "true":
            raise CommandError("Refusing outside DEBUG. Set ALLOW_DEMO_SEED=true on staging.")
        password = os.environ.get("LOAD_TEST_PASSWORD", "load-test-pass-2026")
        with bypass_rls():
            studio, _ = Studio.objects.get_or_create(
                slug="load-test", defaults={"name": "Load Test Studio"}
            )
            Subscription.objects.get_or_create(
                studio=studio, defaults={"status": "active", "plan": Plan.objects.get(code="pro")}
            )
            owner = User.objects.filter(
                email="loadowner@loadtest.test"
            ).first() or User.objects.create_user(
                email="loadowner@loadtest.test",
                password=password,
                full_name="Load Owner",
                studio=studio,
                role="owner",
                email_verified_at=timezone.now(),
            )
            event, _ = Event.objects.get_or_create(
                studio=studio,
                title="Load test wedding",
                defaults={"status": "shared", "created_by": owner},
            )
            Selection.objects.filter(event=event).delete()
            Photo.objects.filter(event=event).delete()
            Photo.objects.bulk_create(
                [
                    Photo(
                        studio=studio,
                        event=event,
                        relative_path=f"Day {i // 1000 + 1}/DSC_{i:05}.NEF",
                        original_filename=f"DSC_{i:05}.NEF",
                        status="ready",
                        width=1600,
                        height=1067,
                        preview_key=f"load/{i}/p.webp",
                        thumb_key=f"load/{i}/t.webp",
                        sort_order=i,
                    )
                    for i in range(photos)
                ],
                batch_size=1000,
            )
            access = ClientAccess.objects.filter(username="loadclient").first() or ClientAccess(
                studio=studio,
                event=event,
                client_name="Load Client",
                email="client@loadtest.test",
                username="loadclient",
            )
            access.event, access.is_active, access.failed_attempts, access.locked_until = (
                event,
                True,
                0,
                None,
            )
            access.set_password(password)
            access.save()
        self.stdout.write(self.style.SUCCESS(f"Load-test event ready with {photos} photos."))
