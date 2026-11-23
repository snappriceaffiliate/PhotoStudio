import json
import logging
from datetime import UTC, datetime

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsStudioMember, IsStudioOwner
from apps.audit.models import record
from apps.core.tenancy import bypass_rls
from apps.events.models import Event

from . import changes, entitlements, razorpay
from .models import Plan, Subscription, VerifiedPayment, WebhookEvent

logger = logging.getLogger(__name__)


def _ts(value) -> datetime | None:
    return datetime.fromtimestamp(value, tz=UTC) if value else None


def _plan_data(plan: Plan) -> dict:
    return {
        "code": plan.code,
        "name": plan.name,
        "price_inr": plan.price_paise / 100,
        "max_active_events": plan.max_active_events,
        "max_photos_per_event": plan.max_photos_per_event,
        "max_staff": plan.max_staff,
        "custom_theme": plan.custom_branding,
        "available": bool(plan.razorpay_plan_id) and razorpay.configured(),
    }


class BillingView(APIView):
    """Everything the billing screen needs."""

    permission_classes = [IsStudioMember]

    def get(self, request):
        sub = entitlements.subscription_for(request.studio_id)
        limits = sub.limits
        return Response(
            {
                **entitlements.summary(request.studio_id),
                "status": sub.status,
                "plan_code": sub.plan.code
                if sub.plan and sub.status != Subscription.Status.TRIALING
                else None,
                "trial_ends_at": sub.trial_ends_at,
                "current_period_end": sub.current_period_end,
                "cancel_at_period_end": sub.cancel_at_period_end,
                "scheduled_plan_code": sub.scheduled_plan.code if sub.scheduled_plan else None,
                "limits": {
                    "max_active_events": limits.max_active_events,
                    "max_photos_per_event": limits.max_photos_per_event,
                    "max_staff": limits.max_staff,
                },
                "usage": {
                    "active_events": Event.objects.for_studio(request.studio_id)
                    .exclude(status=Event.Status.ARCHIVED)
                    .count(),
                    "staff": User.objects.filter(
                        studio_id=request.studio_id, is_active=True
                    ).count(),
                },
                "plans": [_plan_data(p) for p in Plan.objects.filter(is_public=True)],
                "payments_configured": razorpay.configured(),
                "razorpay_key_id": settings.RAZORPAY_KEY_ID,
            }
        )


class SubscribeRequest(serializers.Serializer):
    plan = serializers.SlugField()


def _plan_for(request) -> Plan | None:
    data = SubscribeRequest(data=request.data if request.method == "POST" else request.GET)
    data.is_valid(raise_exception=True)
    plan = Plan.objects.filter(code=data.validated_data["plan"], is_public=True).first()
    return plan if plan and plan.razorpay_plan_id else None


def _quote_data(q: changes.Quote) -> dict:
    return {
        "kind": q.kind,
        "plan": _plan_data(q.plan),
        "charge_now_inr": q.charge_paise / 100,
        "days_left": q.days_left,
        "starts_at": q.starts_at,
    }


NOT_AVAILABLE = Response(
    {"detail": "This plan is not available yet."}, status=status.HTTP_400_BAD_REQUEST
)


class QuoteView(APIView):
    """What choosing a plan would do and cost now, shown before Razorpay Checkout opens."""

    permission_classes = [IsStudioOwner]

    def get(self, request):
        plan = _plan_for(request)
        if plan is None:
            return NOT_AVAILABLE
        try:
            q = changes.quote(entitlements.subscription_for(request.studio_id), plan)
        except changes.ChangeRefused as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_quote_data(q))


class SubscribeView(APIView):
    """Create a Razorpay subscription; the browser then opens Razorpay Checkout for it.

    For a studio already paying, this is a plan change (see changes.py): an upgrade collects
    the prorated difference upfront and starts full billing on the renewal date; a downgrade
    starts on the renewal date with nothing to pay now.
    """

    permission_classes = [IsStudioOwner]

    def post(self, request):
        plan = _plan_for(request)
        if plan is None:
            return NOT_AVAILABLE
        sub = entitlements.subscription_for(request.studio_id)
        try:
            q = changes.quote(sub, plan)
        except changes.ChangeRefused as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        notes = {"studio_id": str(request.studio_id), "plan": plan.code, "change": q.kind}
        try:
            if q.kind == changes.NEW:
                created = razorpay.create_subscription(plan.razorpay_plan_id, notes=notes)
            else:
                created = razorpay.create_subscription(
                    plan.razorpay_plan_id,
                    notes=notes,
                    start_at=int(q.starts_at.timestamp()),
                    upfront_paise=q.charge_paise,
                    upfront_name=f"{plan.name} plan for the {q.days_left} days left this month",
                )
        except razorpay.RazorpayError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        sub.pending_razorpay_subscription_id = created["id"]
        sub.pending_plan = plan
        sub.pending_change = q.kind
        sub.pending_charge_paise = q.charge_paise
        sub.save(
            update_fields=[
                "pending_razorpay_subscription_id",
                "pending_plan",
                "pending_change",
                "pending_charge_paise",
                "updated_at",
            ]
        )
        record(request, "billing.checkout_started", detail=f"{plan.code} ({q.kind})")
        return Response(
            {
                "subscription_id": created["id"],
                "key_id": settings.RAZORPAY_KEY_ID,
                "plan": _plan_data(plan),
                "quote": _quote_data(q),
                "prefill": {"name": request.user.full_name, "email": request.user.email},
                "studio_name": sub.studio.name,
            }
        )


def _not_started(sub: Subscription) -> bool:
    """The studio's Razorpay subscription is approved but its first full charge is still to come
    (a plan change waiting for the renewal date)."""
    return sub.scheduled_plan_id is not None or sub.razorpay_status == "authenticated"


def finish_checkout(sub: Subscription, remote: dict) -> str | None:
    """Make the approved checkout the studio's subscription. Returns the Razorpay subscription
    it replaces when that one must be cancelled, else None. Call inside a transaction."""
    kind = sub.pending_change or changes.NEW
    previous = sub.razorpay_subscription_id
    old_was_running = sub.status == Subscription.Status.ACTIVE and not sub.cancel_at_period_end
    old_not_started = _not_started(sub)
    plan = sub.pending_plan
    if kind == changes.SCHEDULED:
        # The current plan runs to the renewal date; the chosen one takes over then.
        sub.scheduled_plan = plan if plan and plan.pk != sub.plan_id else None
    else:
        sub.plan, sub.scheduled_plan = plan, None
        if kind == changes.NEW:
            sub.current_period_end = _ts(remote.get("current_end")) or sub.current_period_end
    sub.status, sub.past_due_since, sub.cancel_at_period_end = (
        Subscription.Status.ACTIVE,
        None,
        False,
    )
    sub.razorpay_subscription_id = sub.pending_razorpay_subscription_id
    sub.razorpay_status = remote.get("status", sub.razorpay_status)
    sub.pending_razorpay_subscription_id, sub.pending_plan = None, None
    sub.pending_change, sub.pending_charge_paise = "", 0
    sub.save()
    if (
        previous
        and previous != sub.razorpay_subscription_id
        and (old_was_running or old_not_started)
    ):
        return previous
    return None


def cancel_replaced(previous: str | None, kind: str, was_not_started: bool) -> None:
    """Stop the replaced subscription: at once for an upgrade (its paid period is now covered
    by the new plan) or one that never started, else at the end of its paid period."""
    if not previous:
        return
    try:
        razorpay.cancel_subscription(
            previous, at_cycle_end=not (kind == changes.UPGRADE or was_not_started)
        )
    except razorpay.RazorpayError:
        logger.exception("Could not cancel replaced Razorpay subscription %s", previous)


class VerifyRequest(serializers.Serializer):
    razorpay_payment_id = serializers.CharField(max_length=60)
    razorpay_subscription_id = serializers.CharField(max_length=60)
    razorpay_signature = serializers.CharField(max_length=200)


class VerifyView(APIView):
    """Confirms the Checkout payment so the plan starts at once, without waiting for the webhook.

    Accepted only for a checkout that is still pending, only once per payment, and only when
    Razorpay itself reports the subscription as authenticated or active.
    """

    permission_classes = [IsStudioOwner]

    def post(self, request):
        data = VerifyRequest(data=request.data)
        data.is_valid(raise_exception=True)
        payment_id = data.validated_data["razorpay_payment_id"]
        sub = entitlements.subscription_for(request.studio_id)
        refused = Response(
            {"detail": "The payment could not be verified."}, status=status.HTTP_400_BAD_REQUEST
        )
        # Verify against the subscription ID we stored, never the one the browser sent back.
        pending_id = sub.pending_razorpay_subscription_id
        if (
            not sub.pending_plan_id
            or not pending_id
            or not razorpay.payment_signature_valid(
                payment_id, pending_id, data.validated_data["razorpay_signature"]
            )
            or VerifiedPayment.objects.filter(payment_id=payment_id).exists()
        ):
            return refused
        try:
            remote = razorpay.fetch_subscription(pending_id)
        except razorpay.RazorpayError:
            return Response(
                {"detail": "Payment received; your plan starts as soon as Razorpay confirms it."},
                status=status.HTTP_202_ACCEPTED,
            )
        if remote.get("status") not in {"authenticated", "active"}:
            return refused
        with transaction.atomic():
            try:
                with transaction.atomic():
                    VerifiedPayment.objects.create(
                        studio_id=request.studio_id,
                        payment_id=payment_id,
                        razorpay_subscription_id=pending_id,
                    )
            except IntegrityError:
                return refused
            kind, was_not_started = (
                sub.pending_change or changes.NEW,
                _not_started(sub),
            )
            chosen = sub.pending_plan.code
            previous = finish_checkout(sub, remote)
        cancel_replaced(previous, kind, was_not_started)
        record(request, "billing.payment_verified", detail=f"{chosen} ({kind})")
        return Response(entitlements.summary(request.studio_id))


class CancelView(APIView):
    permission_classes = [IsStudioOwner]

    def post(self, request):
        sub = entitlements.subscription_for(request.studio_id)
        if sub.status != Subscription.Status.ACTIVE or not sub.razorpay_subscription_id:
            return Response(
                {"detail": "There is no active plan to cancel."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            # A subscription still waiting for its start date (a plan change) is stopped at once;
            # the current paid period is unaffected either way.
            razorpay.cancel_subscription(
                sub.razorpay_subscription_id, at_cycle_end=not _not_started(sub)
            )
        except razorpay.RazorpayError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        sub.cancel_at_period_end, sub.scheduled_plan = True, None
        sub.save(update_fields=["cancel_at_period_end", "scheduled_plan", "updated_at"])
        record(request, "billing.cancelled", detail="at end of period")
        return Response(entitlements.summary(request.studio_id))


def apply_webhook(event: str, entity: dict, sub: Subscription) -> None:
    """Update a studio's subscription from one Razorpay subscription.* event."""
    sub.razorpay_status = entity.get("status", sub.razorpay_status)
    if entity.get("current_end"):
        sub.current_period_end = _ts(entity["current_end"])
    plan = (
        Plan.objects.filter(razorpay_plan_id=entity.get("plan_id")).first()
        if entity.get("plan_id")
        else None
    )
    if event in {"subscription.activated", "subscription.charged", "subscription.resumed"}:
        sub.status, sub.past_due_since = Subscription.Status.ACTIVE, None
        # Without a plan ID in the event, fall back to the plan bought at checkout (never to one
        # still waiting in an unfinished checkout).
        bought = sub.pending_plan if sub.pending_razorpay_subscription_id is None else None
        sub.plan = plan or bought or sub.plan
        if sub.pending_razorpay_subscription_id is None:
            sub.pending_plan = None
        sub.scheduled_plan = None
    elif event in {"subscription.pending", "subscription.halted", "subscription.paused"}:
        sub.status = Subscription.Status.PAST_DUE
        sub.past_due_since = sub.past_due_since or timezone.now()
    elif event == "subscription.cancelled":
        sub.status = Subscription.Status.CANCELLED
    elif event in {"subscription.completed", "subscription.expired"}:
        sub.status = Subscription.Status.EXPIRED
    elif event == "subscription.updated" and plan:
        sub.plan = plan
    sub.save()


@csrf_exempt
@require_POST
def webhook(request):
    """Razorpay webhook endpoint. Always answers 2xx once the signature is valid, so
    Razorpay stops retrying; unknown subscriptions are kept for support to look at."""
    body = request.body
    if not razorpay.webhook_signature_valid(body, request.headers.get("X-Razorpay-Signature", "")):
        return HttpResponse(status=400)
    payload = json.loads(body)
    event = payload.get("event", "")
    entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
    event_id = (
        request.headers.get("X-Razorpay-Event-Id")
        or f"{event}:{entity.get('id')}:{payload.get('created_at')}"
    )
    with bypass_rls(), transaction.atomic():
        try:
            with transaction.atomic():
                record_row = WebhookEvent.objects.create(
                    event_id=event_id,
                    event=event,
                    razorpay_subscription_id=entity.get("id", ""),
                    payload=payload,
                )
        except IntegrityError:
            return HttpResponse(status=200)  # already handled this delivery
        sub = (
            Subscription.objects.select_for_update()
            .filter(
                Q(razorpay_subscription_id=entity.get("id"))
                | Q(pending_razorpay_subscription_id=entity.get("id"))
            )
            .first()
            if event.startswith("subscription.") and entity.get("id")
            else None
        )
        replaced = None
        if sub is not None and sub.pending_razorpay_subscription_id == entity.get("id"):
            # Approved in Razorpay but the browser never confirmed (closed too early).
            if event in {
                "subscription.authenticated",
                "subscription.activated",
                "subscription.charged",
            }:
                kind, was_not_started = (
                    sub.pending_change or changes.NEW,
                    _not_started(sub),
                )
                replaced = (finish_checkout(sub, entity), kind, was_not_started)
            else:
                sub = None  # a checkout that was never approved changes nothing
        if sub is not None:
            if event != "subscription.authenticated":
                apply_webhook(event, entity, sub)
            record_row.processed = True
            record_row.save(update_fields=["processed"])
    if replaced:
        cancel_replaced(*replaced)
    return HttpResponse(status=200)
