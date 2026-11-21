"""Plan limits and subscription state, checked by the API before changes that cost money.

When a studio's trial or subscription has lapsed, it can still sign in, see its events and
download selections, but cannot create events, upload, share with clients or add staff.
"""

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException

from .models import Access, Limits, Subscription


class BillingBlocked(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "billing"


def subscription_for(studio_id) -> Subscription:
    sub = Subscription.objects.for_studio(studio_id).select_related("plan", "studio").first()
    if sub is None:  # studios always get one at sign-up; this covers older data
        from apps.studios.models import Studio

        sub = Subscription.start_trial(Studio.objects.get(pk=studio_id))
    return sub


def access_for(studio_id) -> Access:
    return subscription_for(studio_id).access()


def limits_for(studio_id) -> Limits:
    return subscription_for(studio_id).limits


def require_can_work(studio_id) -> Subscription:
    sub = subscription_for(studio_id)
    access = sub.access()
    if not access.can_work:
        raise BillingBlocked(access.message)
    return sub


def check_event_limit(studio_id) -> None:
    from apps.events.models import Event

    sub = require_can_work(studio_id)
    limit = sub.limits.max_active_events
    if limit is None:
        return
    active = Event.objects.for_studio(studio_id).exclude(status=Event.Status.ARCHIVED).count()
    if active >= limit:
        raise BillingBlocked(
            f"Your {sub.limits.name} plan allows {limit} active event{'s' if limit != 1 else ''}. "
            "Archive a finished event or choose a bigger plan."
        )


def photo_limit(studio_id) -> int:
    return min(settings.MAX_PHOTOS_PER_EVENT, limits_for(studio_id).max_photos_per_event)


def check_staff_limit(studio_id) -> None:
    from apps.accounts.models import User

    sub = require_can_work(studio_id)
    members = User.objects.filter(studio_id=studio_id, is_active=True).count()
    if members >= sub.limits.max_staff:
        raise BillingBlocked(
            f"Your {sub.limits.name} plan allows {sub.limits.max_staff} people. "
            "Remove someone or choose a bigger plan."
        )


def require_branding(studio_id) -> Subscription:
    sub = require_can_work(studio_id)
    if not sub.limits.custom_branding:
        raise BillingBlocked(
            f"Your {sub.limits.name} plan does not include a custom theme and logo. "
            "Choose the Studio or Pro plan."
        )
    return sub


def branding_allowed(studio_id) -> bool:
    return limits_for(studio_id).custom_branding


def summary(studio_id) -> dict:
    sub = subscription_for(studio_id)
    access = sub.access()
    return {
        "state": access.state,
        "can_work": access.can_work,
        "gallery_open": access.gallery_open,
        "message": access.message,
        "until": access.until,
        "plan": sub.limits.name,
    }
