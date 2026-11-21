from collections import defaultdict

from django.utils import timezone
from procrastinate.contrib.django import app

from apps.accounts.models import User
from apps.core.tenancy import bypass_rls
from apps.notifications import emails

from .reminders import due_reminders


@app.periodic(cron="30 4 * * *")  # every morning at 04:30 UTC (10:00 in India)
@app.task(name="clients.remind_studios", queueing_lock="clients.remind_studios")
def remind_studios(timestamp: int) -> int:
    """Email each studio owner the clients who became due for a reminder since the last email."""
    now = timezone.now()
    emailed = 0
    with bypass_rls():
        by_studio = defaultdict(list)
        for item in due_reminders(now=now):
            by_studio[item.access.studio_id].append(item)
        for studio_id, items in by_studio.items():
            new = [
                i
                for i in items
                if not i.access.reminder_emailed_at or i.access.reminder_emailed_at < i.since
            ]
            if not new:
                continue
            owners = User.objects.filter(studio_id=studio_id, role=User.Role.OWNER, is_active=True)
            for owner in owners:
                emails.reminders_due_email(owner, items)
                emailed += 1
            for i in new:
                i.access.reminder_emailed_at = now
                i.access.save(update_fields=["reminder_emailed_at", "updated_at"])
    return emailed
