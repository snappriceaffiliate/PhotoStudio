"""Changing plan while a paid period is running.

Razorpay's own "update subscription" cannot change UPI Autopay subscriptions, which most
studios use, so a change is always a new Razorpay subscription:

- Upgrade (dearer plan): the new limits apply at once. The customer pays now only the price
  difference for the days left in the paid period, collected as an upfront add-on when they
  approve the new subscription. The new subscription's first full charge is on the old
  renewal date, so nobody gets the dearer plan cheaply and nobody pays twice.
- Downgrade (cheaper plan), or keeping a plan that was cancelled: nothing is charged now; the
  new subscription starts on the renewal date and the current plan runs until then.

The old subscription is cancelled once the new one is approved: at once for an upgrade, at
the end of the paid period for a downgrade.
"""

import calendar
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from .models import Plan, Subscription

NEW = "new"  # no paid period running: an ordinary subscription starting now
UPGRADE = "upgrade"
SCHEDULED = "scheduled"  # starts on the renewal date

# Razorpay will not collect less than ₹1; a smaller difference is not charged.
MIN_CHARGE_PAISE = 100


class ChangeRefused(Exception):
    pass


@dataclass(frozen=True)
class Quote:
    kind: str
    plan: Plan
    charge_paise: int = 0
    days_left: int = 0
    starts_at: datetime | None = None  # when the new subscription's first full charge falls


def period_start(end: datetime) -> datetime:
    """The start of the monthly period that ends at `end` (same day of the previous month)."""
    year, month = (end.year, end.month - 1) if end.month > 1 else (end.year - 1, 12)
    return end.replace(
        year=year, month=month, day=min(end.day, calendar.monthrange(year, month)[1])
    )


def has_paid_period(sub: Subscription, now: datetime) -> bool:
    return (
        sub.plan_id is not None
        and sub.status in (Subscription.Status.ACTIVE, Subscription.Status.CANCELLED)
        and sub.current_period_end is not None
        and sub.current_period_end > now
    )


def quote(sub: Subscription, plan: Plan, now: datetime | None = None) -> Quote:
    now = now or timezone.now()
    if sub.status == Subscription.Status.PAST_DUE:
        raise ChangeRefused(
            "Your last payment did not go through. Once Razorpay collects it you can change plan."
        )
    if not has_paid_period(sub, now):
        return Quote(NEW, plan)
    current = sub.plan
    ending = sub.cancel_at_period_end or sub.status == Subscription.Status.CANCELLED
    if plan.pk == current.pk and not ending and sub.scheduled_plan_id is None:
        raise ChangeRefused(f"You are already on the {plan.name} plan.")
    if plan.pk == sub.scheduled_plan_id:
        raise ChangeRefused(f"You already switch to the {plan.name} plan on the renewal date.")
    end = sub.current_period_end
    if plan.price_paise > current.price_paise:
        start = period_start(end)
        left = (end - now).total_seconds() / (end - start).total_seconds()
        charge = round((plan.price_paise - current.price_paise) * min(1.0, max(0.0, left)))
        return Quote(
            UPGRADE,
            plan,
            charge_paise=charge if charge >= MIN_CHARGE_PAISE else 0,
            days_left=max(1, round((end - now).total_seconds() / 86400)),
            starts_at=end,
        )
    return Quote(SCHEDULED, plan, starts_at=end)
