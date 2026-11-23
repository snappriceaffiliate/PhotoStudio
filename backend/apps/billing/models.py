"""Subscription plans, each studio's subscription, and Razorpay webhook records."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TenantModel, TimestampedModel


class Plan(TimestampedModel):
    """A subscription plan. Prices and limits are edited in the Django admin."""

    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=60)
    price_paise = models.PositiveIntegerField(help_text="Monthly price in paise: 99900 is ₹999.")
    max_active_events = models.PositiveIntegerField(
        null=True, blank=True, help_text="Empty: unlimited."
    )
    max_photos_per_event = models.PositiveIntegerField()
    max_staff = models.PositiveIntegerField(help_text="Studio members, including the owner.")
    custom_branding = models.BooleanField(
        default=True, help_text="Studio logo and colour in client galleries."
    )
    razorpay_plan_id = models.CharField(
        max_length=40, blank=True, help_text="Set by sync_razorpay_plans."
    )
    is_public = models.BooleanField(default=True, help_text="Shown on the billing screen.")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "price_paise"]

    def __str__(self) -> str:
        return f"{self.name} (₹{self.price_paise / 100:,.0f}/month)"


@dataclass(frozen=True)
class Limits:
    name: str
    max_active_events: int | None
    max_photos_per_event: int
    max_staff: int
    custom_branding: bool = True


def trial_limits() -> Limits:
    """The trial includes branding so studios can see their galleries as clients will.
    The number of active events is a setting (TRIAL_MAX_ACTIVE_EVENTS) so it can be raised
    for testing without a release."""
    return Limits(
        "Free trial",
        max_active_events=settings.TRIAL_MAX_ACTIVE_EVENTS,
        max_photos_per_event=5000,
        max_staff=2,
    )


@dataclass(frozen=True)
class Access:
    """What a studio may do right now, given its subscription."""

    state: str  # trial, active, payment_due, ending, lapsed
    can_work: bool  # create events, upload, share, invite staff
    gallery_open: bool  # clients can still open galleries
    message: str
    until: datetime | None = None


class Subscription(TenantModel):
    """One per studio. Starts as a trial; becomes ACTIVE once the first payment succeeds."""

    class Status(models.TextChoices):
        TRIALING = "trialing", "Free trial"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Payment due"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Ended"

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TRIALING)
    plan = models.ForeignKey(
        Plan, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    pending_plan = models.ForeignKey(
        Plan,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Plan chosen at checkout, until the payment is confirmed.",
    )
    # Checkout in progress: the Razorpay subscription being approved and what it does.
    pending_razorpay_subscription_id = models.CharField(
        max_length=40, null=True, blank=True, unique=True
    )
    pending_change = models.CharField(max_length=10, blank=True)
    pending_charge_paise = models.PositiveIntegerField(default=0)
    scheduled_plan = models.ForeignKey(
        Plan,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Plan that takes over on the renewal date (a downgrade).",
    )
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    past_due_since = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    razorpay_subscription_id = models.CharField(max_length=40, null=True, blank=True, unique=True)
    razorpay_status = models.CharField(max_length=20, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["studio"], name="one_subscription_per_studio")
        ]

    def __str__(self) -> str:
        return f"{self.studio_id}: {self.status}"

    @classmethod
    def start_trial(cls, studio):
        return cls.objects.create(
            studio=studio,
            status=cls.Status.TRIALING,
            trial_ends_at=timezone.now() + timedelta(days=settings.TRIAL_DAYS),
        )

    @property
    def limits(self) -> Limits:
        if self.status == self.Status.TRIALING or self.plan is None:
            return trial_limits()
        p = self.plan
        return Limits(
            p.name, p.max_active_events, p.max_photos_per_event, p.max_staff, p.custom_branding
        )

    def access(self, now: datetime | None = None) -> Access:
        now = now or timezone.now()
        grace = timedelta(days=settings.BILLING_GRACE_DAYS)

        def lapsed(since: datetime | None, why: str) -> Access:
            since = since or now
            open_until = since + grace
            return Access(
                "lapsed",
                False,
                now < open_until,
                f"{why} Choose a plan to keep working. Existing events and selections stay available to you.",
                open_until,
            )

        if self.status == self.Status.TRIALING:
            if self.trial_ends_at and now >= self.trial_ends_at:
                return lapsed(self.trial_ends_at, "Your free trial has ended.")
            return Access("trial", True, True, "Free trial", self.trial_ends_at)
        if self.status == self.Status.ACTIVE:
            # Without a renewal webhook, a paid period still runs out (after the grace days).
            if self.current_period_end and now >= self.current_period_end + grace:
                return lapsed(
                    self.current_period_end + grace, "Your subscription payment did not go through."
                )
            if self.cancel_at_period_end and self.current_period_end:
                return Access(
                    "ending",
                    True,
                    True,
                    "Your plan ends at the end of this period.",
                    self.current_period_end,
                )
            return Access("active", True, True, "Active", self.current_period_end)
        if self.status == self.Status.PAST_DUE:
            since = self.past_due_since or now
            if now < since + grace:
                return Access(
                    "payment_due",
                    True,
                    True,
                    "Your last payment did not go through. Razorpay will retry; check your payment method.",
                    since + grace,
                )
            return lapsed(since + grace, "Your subscription payment did not go through.")
        if (
            self.status == self.Status.CANCELLED
            and self.current_period_end
            and now < self.current_period_end
        ):
            return Access(
                "ending",
                True,
                True,
                "Your plan is cancelled and ends soon.",
                self.current_period_end,
            )
        return lapsed(self.current_period_end, "Your subscription has ended.")


class VerifiedPayment(TenantModel):
    """Each Checkout payment accepted once; a replayed confirmation is refused."""

    payment_id = models.CharField(max_length=60, unique=True)
    razorpay_subscription_id = models.CharField(max_length=40)


class WebhookEvent(TimestampedModel):
    """Every Razorpay webhook received, kept for de-duplication and support."""

    event_id = models.CharField(max_length=60, unique=True)
    event = models.CharField(max_length=60)
    razorpay_subscription_id = models.CharField(max_length=40, blank=True)
    payload = models.JSONField()
    processed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
