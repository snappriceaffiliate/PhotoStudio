import json
import logging
from datetime import UTC, datetime

from django.conf import settings
from django.db import IntegrityError, transaction
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

from . import entitlements, razorpay
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


class SubscribeView(APIView):
    """Create a Razorpay subscription; the browser then opens Razorpay Checkout for it."""

    permission_classes = [IsStudioOwner]

    def post(self, request):
        data = SubscribeRequest(data=request.data)
        data.is_valid(raise_exception=True)
        plan = Plan.objects.filter(code=data.validated_data["plan"], is_public=True).first()
        if plan is None or not plan.razorpay_plan_id:
            return Response(
                {"detail": "This plan is not available yet."}, status=status.HTTP_400_BAD_REQUEST
            )
        sub = entitlements.subscription_for(request.studio_id)
        if sub.status == Subscription.Status.ACTIVE and not sub.cancel_at_period_end:
            return Response(
                {
                    "detail": "You already have an active plan. Plan changes are not available yet; contact support."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            created = razorpay.create_subscription(
                plan.razorpay_plan_id,
                notes={"studio_id": str(request.studio_id), "plan": plan.code},
            )
        except razorpay.RazorpayError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        sub.razorpay_subscription_id = created["id"]
        sub.razorpay_status = created.get("status", "")
        sub.pending_plan = plan
        sub.save(
            update_fields=[
                "razorpay_subscription_id",
                "razorpay_status",
                "pending_plan",
                "updated_at",
            ]
        )
        record(request, "billing.checkout_started", detail=plan.code)
        return Response(
            {
                "subscription_id": created["id"],
                "key_id": settings.RAZORPAY_KEY_ID,
                "plan": _plan_data(plan),
                "prefill": {"name": request.user.full_name, "email": request.user.email},
                "studio_name": sub.studio.name,
            }
        )


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
        if (
            not sub.pending_plan_id
            or not sub.razorpay_subscription_id
            or not razorpay.payment_signature_valid(
                payment_id, sub.razorpay_subscription_id, data.validated_data["razorpay_signature"]
            )
            or VerifiedPayment.objects.filter(payment_id=payment_id).exists()
        ):
            return refused
        try:
            remote = razorpay.fetch_subscription(sub.razorpay_subscription_id)
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
                        razorpay_subscription_id=sub.razorpay_subscription_id,
                    )
            except IntegrityError:
                return refused
            sub.status, sub.past_due_since, sub.cancel_at_period_end = (
                Subscription.Status.ACTIVE,
                None,
                False,
            )
            sub.plan, sub.pending_plan = sub.pending_plan, None
            sub.current_period_end = _ts(remote.get("current_end")) or sub.current_period_end
            sub.razorpay_status = remote.get("status", "")
            sub.save()
        record(request, "billing.payment_verified", detail=sub.plan.code)
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
            razorpay.cancel_subscription(sub.razorpay_subscription_id, at_cycle_end=True)
        except razorpay.RazorpayError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        sub.cancel_at_period_end = True
        sub.save(update_fields=["cancel_at_period_end", "updated_at"])
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
        sub.plan = plan or sub.pending_plan or sub.plan
        sub.pending_plan = None
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
            .filter(razorpay_subscription_id=entity.get("id"))
            .first()
            if event.startswith("subscription.") and entity.get("id")
            else None
        )
        if sub is not None:
            apply_webhook(event, entity, sub)
            record_row.processed = True
            record_row.save(update_fields=["processed"])
    return HttpResponse(status=200)
