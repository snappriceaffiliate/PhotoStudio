"""Which clients should get a reminder to choose their photos.

A client who has not submitted is due a reminder 2 days after the gallery was shared with
them, then every 3 days, at most 3 times; and once on the day before the gallery expires.
The studio sends the reminder from its own WhatsApp (the server cannot send WhatsApp
messages), so "sent" is recorded when the studio taps the button. Each morning the owner
gets an email listing clients who became due since the last email.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from apps.billing.entitlements import access_for
from apps.events.models import Event

from .models import ClientAccess

FIRST_AFTER = timedelta(days=2)
AGAIN_AFTER = timedelta(days=3)
MAX_REMINDERS = 3


@dataclass
class Due:
    access: ClientAccess
    reason: str  # "first", "again" or "expiring"
    since: datetime


def _start_of(day) -> datetime:
    return timezone.make_aware(datetime.combine(day, datetime.min.time()))


def due_reason(access: ClientAccess, now: datetime) -> Due | None:
    event = access.event
    today = timezone.localdate(now)
    if event.expires_at and event.expires_at < today:
        return None
    reminded_today = (
        access.last_reminded_at and timezone.localdate(access.last_reminded_at) >= today
    )
    if event.expires_at and event.expires_at == today + timedelta(days=1) and not reminded_today:
        return Due(access, "expiring", _start_of(today))
    if access.reminder_count == 0:
        since = access.created_at + FIRST_AFTER
        return Due(access, "first", since) if now >= since else None
    if access.reminder_count < MAX_REMINDERS and access.last_reminded_at:
        since = access.last_reminded_at + AGAIN_AFTER
        return Due(access, "again", since) if now >= since else None
    return None


def due_reminders(accesses=None, now: datetime | None = None) -> list[Due]:
    """Reminders due now, oldest first. Pass a studio's ClientAccess queryset, or none for all
    studios (the caller must then bypass row-level security)."""
    now = now or timezone.now()
    qs = accesses if accesses is not None else ClientAccess.objects.all()
    qs = qs.filter(
        is_active=True,
        role=ClientAccess.Role.MAIN,  # only the main client can submit
        event__status=Event.Status.SHARED,
        event__submission__isnull=True,
    ).select_related("event", "studio")
    open_studios: dict = {}
    due = []
    for access in qs:
        if access.studio_id not in open_studios:
            open_studios[access.studio_id] = access_for(access.studio_id).gallery_open
        if not open_studios[access.studio_id]:
            continue
        item = due_reason(access, now)
        if item:
            due.append(item)
    return sorted(due, key=lambda d: d.since)


def mark_sent(access: ClientAccess, now: datetime | None = None) -> None:
    access.reminder_count += 1
    access.last_reminded_at = now or timezone.now()
    access.save(update_fields=["reminder_count", "last_reminded_at", "updated_at"])
