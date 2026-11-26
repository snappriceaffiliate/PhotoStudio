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


def over_limits(studio_id, plan) -> list[str]:
    """What the studio has beyond `plan`'s limits, as sentences for the plan-change screens.
    Nothing is deleted on a downgrade: extra staff logins are turned off when the plan starts
    (see turn_off_extra_staff); events and photos stay, but no more can be added."""
    from django.db.models import Count

    from apps.accounts.models import User
    from apps.events.models import Event
    from apps.studios.models import Studio

    notes = []
    people = User.objects.filter(studio_id=studio_id, is_active=True).count()
    if people > plan.max_staff:
        extra = people - plan.max_staff
        notes.append(
            f"You have {people} people; {plan.name} allows {plan.max_staff}. When it starts, "
            f"the {_count(extra, 'newest staff login')} {'is' if extra == 1 else 'are'} turned "
            "off. To choose who keeps access, remove people on the Staff page first."
        )
    events = Event.objects.for_studio(studio_id).exclude(status=Event.Status.ARCHIVED)
    active = events.count()
    if plan.max_active_events is not None and active > plan.max_active_events:
        notes.append(
            f"You have {active} active events; {plan.name} allows {plan.max_active_events}. "
            "They stay open for your clients, but you cannot create new events until you "
            f"archive {active - plan.max_active_events}."
        )
    max_photos = min(settings.MAX_PHOTOS_PER_EVENT, plan.max_photos_per_event)
    big = events.annotate(n=Count("photos")).filter(n__gt=max_photos).count()
    if big:
        notes.append(
            f"{_count(big, 'event')} {'has' if big == 1 else 'have'} more than "
            f"{max_photos:,} photos, the most {plan.name} allows. The photos stay, but you "
            "cannot add more to "
            f"{'it' if big == 1 else 'them'}."
        )
    studio = Studio.objects.filter(pk=studio_id).only("logo_key", "accent_color").first()
    if not plan.custom_branding and studio and (studio.logo_key or studio.accent_color):
        notes.append(
            f"{plan.name} does not include a custom theme, so client galleries show the "
            "standard look. Your logo and colours stay saved for when you upgrade again."
        )
    return notes


def turn_off_extra_staff(sub: Subscription) -> list:
    """After a move to a smaller plan, turn off the newest staff logins beyond its limit.
    The owner is never turned off, and can turn people back on from the Staff page."""
    from apps.accounts.models import User

    active = User.objects.filter(studio_id=sub.studio_id, is_active=True)
    extra = active.count() - sub.limits.max_staff
    if extra <= 0:
        return []
    members = list(active.exclude(role=User.Role.OWNER).order_by("-date_joined")[:extra])
    # Django refuses sessions of inactive users, so access ends on their next request.
    User.objects.filter(pk__in=[m.pk for m in members]).update(is_active=False)
    return members


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


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
