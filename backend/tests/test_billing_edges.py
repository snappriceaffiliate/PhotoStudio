"""Billing edge cases: refusals, Razorpay outages, and the less common webhook events."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing import razorpay
from apps.billing.models import Plan, Subscription

from .test_billing import (  # noqa: F401 - shared fixtures and helpers
    owner_on_trial,
    quiet_email,
    razorpay_keys,
    set_subscription,
    sign,
    subscription,
    webhook,
)

pytestmark = pytest.mark.django_db


def go_active(studio, **extra):
    set_subscription(
        studio,
        status="active",
        plan=Plan.objects.get(code="studio"),
        razorpay_subscription_id="sub_9",
        current_period_end=timezone.now() + timedelta(days=20),
        **extra,
    )


def razorpay_down(*args, **kwargs):
    raise razorpay.RazorpayError("Could not reach Razorpay. Try again in a minute.")


class TestSubscribe:
    def test_an_active_plan_cannot_be_bought_again(self, api, owner_on_trial, razorpay_keys):
        go_active(owner_on_trial[0])
        response = api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})
        assert response.status_code == 400
        assert response.json()["detail"] == "You are already on the Studio plan."

    def test_a_cancelling_plan_can_be_bought_again(
        self, api, owner_on_trial, razorpay_keys, monkeypatch
    ):
        go_active(owner_on_trial[0], cancel_at_period_end=True)
        monkeypatch.setattr(razorpay, "create_subscription", lambda *a, **k: {"id": "sub_new"})
        assert api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"}).status_code == 200

    def test_razorpay_being_down_is_reported_not_crashed(
        self, api, owner_on_trial, razorpay_keys, monkeypatch
    ):
        monkeypatch.setattr(razorpay, "create_subscription", razorpay_down)
        response = api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})
        assert response.status_code == 502
        assert "Could not reach Razorpay" in response.json()["detail"]
        assert subscription(owner_on_trial[0]).status == "trialing"

    def test_unknown_plan_is_refused(self, api, owner_on_trial, razorpay_keys):
        assert api.json("post", "/api/v1/billing/subscribe", {"plan": "nope"}).status_code == 400


class TestVerify:
    def test_payment_is_kept_when_razorpay_cannot_confirm_yet(
        self, api, owner_on_trial, razorpay_keys, monkeypatch
    ):
        monkeypatch.setattr(razorpay, "create_subscription", lambda *a, **k: {"id": "sub_1"})
        api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})
        monkeypatch.setattr(razorpay, "fetch_subscription", razorpay_down)
        response = api.json(
            "post",
            "/api/v1/billing/verify",
            {
                "razorpay_payment_id": "pay_1",
                "razorpay_subscription_id": "sub_1",
                "razorpay_signature": sign("pay_1", "sub_1"),
            },
        )
        assert response.status_code == 202
        assert subscription(owner_on_trial[0]).status == "trialing"  # webhook finishes the job

    def test_an_unconfirmed_subscription_does_not_activate(
        self, api, owner_on_trial, razorpay_keys, monkeypatch
    ):
        monkeypatch.setattr(razorpay, "create_subscription", lambda *a, **k: {"id": "sub_1"})
        api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})
        monkeypatch.setattr(razorpay, "fetch_subscription", lambda sid: {"status": "created"})
        response = api.json(
            "post",
            "/api/v1/billing/verify",
            {
                "razorpay_payment_id": "pay_1",
                "razorpay_subscription_id": "sub_1",
                "razorpay_signature": sign("pay_1", "sub_1"),
            },
        )
        assert response.status_code != 200 or response.json()["state"] != "active"
        assert subscription(owner_on_trial[0]).status == "trialing"


class TestCancel:
    def test_nothing_to_cancel_on_a_trial(self, api, owner_on_trial, razorpay_keys):
        response = api.json("post", "/api/v1/billing/cancel")
        assert response.status_code == 400
        assert "no active plan" in response.json()["detail"]

    def test_razorpay_failure_leaves_the_plan_unchanged(
        self, api, owner_on_trial, razorpay_keys, monkeypatch
    ):
        go_active(owner_on_trial[0])
        monkeypatch.setattr(razorpay, "cancel_subscription", razorpay_down)
        assert api.json("post", "/api/v1/billing/cancel").status_code == 502
        assert subscription(owner_on_trial[0]).cancel_at_period_end is False


class TestMoreWebhooks:
    @pytest.fixture
    def active(self, make_studio, razorpay_keys):
        studio, _ = make_studio("alpha")
        go_active(studio)
        return studio

    @pytest.mark.parametrize("event", ["subscription.completed", "subscription.expired"])
    def test_a_finished_subscription_expires(self, active, event):
        assert webhook(event, {"id": "sub_9"}, event_id=f"evt_{event}").status_code == 200
        assert subscription(active).status == Subscription.Status.EXPIRED

    def test_events_for_other_topics_are_acknowledged_and_ignored(self, active):
        assert webhook("payment.captured", {"id": "sub_9"}, event_id="evt_x").status_code == 200
        assert subscription(active).status == "active"
