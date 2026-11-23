"""Changing plan while paying: prorated upgrades now, downgrades on the renewal date."""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.billing import changes, razorpay
from apps.billing.models import Plan, Subscription
from apps.core import tenancy

from .conftest import PASSWORD
from .test_billing import quiet_email, sign, subscription, webhook  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def keys(settings):
    settings.RAZORPAY_KEY_ID = "rzp_test_123"
    settings.RAZORPAY_KEY_SECRET = "test_key_secret"
    settings.RAZORPAY_WEBHOOK_SECRET = "test_webhook_secret"
    with tenancy.bypass_rls():
        for code in ("starter", "studio", "pro"):
            Plan.objects.filter(code=code).update(razorpay_plan_id=f"plan_{code}")


@pytest.fixture
def fake_razorpay(monkeypatch):
    calls = {"create": [], "cancel": []}

    def create(plan_id, notes, start_at=None, upfront_paise=0, upfront_name=""):
        calls["create"].append(
            {"plan_id": plan_id, "start_at": start_at, "upfront": upfront_paise, "notes": notes}
        )
        return {"id": f"sub_new{len(calls['create'])}", "status": "created"}

    monkeypatch.setattr(razorpay, "create_subscription", create)
    monkeypatch.setattr(
        razorpay,
        "cancel_subscription",
        lambda sid, at_cycle_end: calls["cancel"].append((sid, at_cycle_end)) or {},
    )
    monkeypatch.setattr(razorpay, "fetch_subscription", lambda sid: {"status": "authenticated"})
    return calls


def on_plan(studio, code, days_left=3, **extra):
    with tenancy.bypass_rls():
        Subscription.objects.filter(studio=studio).update(
            status="active",
            plan=Plan.objects.get(code=code),
            razorpay_subscription_id="sub_old",
            razorpay_status="active",
            current_period_end=timezone.now() + timedelta(days=days_left),
            **extra,
        )


@pytest.fixture
def owner(api, make_studio, keys):
    studio, user = make_studio("alpha")
    api.json("post", "/api/v1/auth/login", {"email": user.email, "password": PASSWORD})
    return studio


def approve(api, sub_id="sub_new1", pay="pay_1"):
    return api.json(
        "post",
        "/api/v1/billing/verify",
        {
            "razorpay_payment_id": pay,
            "razorpay_subscription_id": sub_id,
            "razorpay_signature": sign(pay, sub_id),
        },
    )


class TestQuote:
    def plans(self):
        return Plan.objects.get(code="starter"), Plan.objects.get(code="studio")

    def sub(self, plan, end):
        return Subscription(status="active", plan=plan, current_period_end=end)

    def test_upgrade_charges_only_the_difference_for_the_days_left(self):
        starter, studio = self.plans()
        end = datetime(2026, 12, 21, tzinfo=UTC)  # period 21 Nov to 21 Dec: 30 days
        q = changes.quote(self.sub(starter, end), studio, now=end - timedelta(days=3))
        gap = studio.price_paise - starter.price_paise
        assert (q.kind, q.days_left, q.starts_at) == ("upgrade", 3, end)
        assert q.charge_paise == round(gap * 3 / 30)

    def test_upgrade_on_the_first_day_costs_the_full_difference(self):
        starter, studio = self.plans()
        end = datetime(2026, 12, 21, tzinfo=UTC)
        q = changes.quote(self.sub(starter, end), studio, now=end - timedelta(days=30))
        assert q.charge_paise == studio.price_paise - starter.price_paise

    def test_a_difference_under_one_rupee_is_not_charged(self):
        starter, studio = self.plans()
        end = datetime(2026, 12, 21, tzinfo=UTC)
        q = changes.quote(self.sub(starter, end), studio, now=end - timedelta(seconds=10))
        assert (q.kind, q.charge_paise) == ("upgrade", 0)

    def test_downgrade_waits_for_the_renewal_date(self):
        starter, studio = self.plans()
        end = datetime(2026, 12, 21, tzinfo=UTC)
        q = changes.quote(self.sub(studio, end), starter, now=end - timedelta(days=10))
        assert (q.kind, q.charge_paise, q.starts_at) == ("scheduled", 0, end)

    def test_no_paid_period_is_an_ordinary_new_subscription(self):
        starter, _ = self.plans()
        assert changes.quote(Subscription(status="trialing"), starter).kind == "new"

    def test_period_start_handles_short_months(self):
        assert changes.period_start(datetime(2026, 3, 31, tzinfo=UTC)).day == 28


class TestUpgrade:
    def test_new_limits_now_difference_upfront_full_price_from_renewal(
        self, api, owner, fake_razorpay
    ):
        on_plan(owner, "starter", days_left=3)
        renews = subscription(owner).current_period_end
        quote = api.json("get", "/api/v1/billing/quote?plan=studio").json()
        assert quote["kind"] == "upgrade" and quote["days_left"] == 3
        assert 0 < quote["charge_now_inr"] < 1500 * 4 / 30

        started = api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})
        assert started.status_code == 200
        (created,) = fake_razorpay["create"]
        assert created["plan_id"] == "plan_studio"
        assert created["start_at"] == int(renews.timestamp())
        assert created["upfront"] == round(quote["charge_now_inr"] * 100)
        assert subscription(owner).plan.code == "starter"  # nothing changes before approval

        assert approve(api).status_code == 200
        sub = subscription(owner)
        assert (sub.plan.code, sub.razorpay_subscription_id, sub.current_period_end) == (
            "studio",
            "sub_new1",
            renews,
        )
        assert fake_razorpay["cancel"] == [("sub_old", False)]  # old one stops at once
        assert api.json("get", "/api/v1/billing").json()["limits"]["max_staff"] == 3

    def test_finished_by_webhook_when_the_browser_closed_early(self, api, owner, fake_razorpay):
        on_plan(owner, "starter")
        api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})
        webhook("subscription.authenticated", {"id": "sub_new1", "status": "authenticated"})
        sub = subscription(owner)
        assert (sub.plan.code, sub.razorpay_subscription_id) == ("studio", "sub_new1")
        assert fake_razorpay["cancel"] == [("sub_old", False)]

    def test_an_unapproved_checkout_does_not_disturb_renewals(self, api, owner, fake_razorpay):
        on_plan(owner, "starter")
        api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})
        webhook(
            "subscription.charged",
            {
                "id": "sub_old",
                "status": "active",
                "plan_id": "plan_starter",
                "current_end": 1893456000,
            },
        )
        webhook("subscription.cancelled", {"id": "sub_new1", "status": "cancelled"}, "evt_2")
        sub = subscription(owner)
        assert (sub.plan.code, sub.status, sub.razorpay_subscription_id) == (
            "starter",
            "active",
            "sub_old",
        )
        assert sub.current_period_end.year == 2030


class TestDowngrade:
    def test_current_plan_runs_to_renewal_then_the_cheaper_one_starts(
        self, api, owner, fake_razorpay
    ):
        on_plan(owner, "studio", days_left=10)
        renews = subscription(owner).current_period_end
        quote = api.json("get", "/api/v1/billing/quote?plan=starter").json()
        assert (quote["kind"], quote["charge_now_inr"]) == ("scheduled", 0)

        api.json("post", "/api/v1/billing/subscribe", {"plan": "starter"})
        assert fake_razorpay["create"][0]["upfront"] == 0
        assert fake_razorpay["create"][0]["start_at"] == int(renews.timestamp())
        approve(api)
        sub = subscription(owner)
        assert (sub.plan.code, sub.scheduled_plan.code) == ("studio", "starter")
        assert fake_razorpay["cancel"] == [("sub_old", True)]  # old one stops at renewal
        billing = api.json("get", "/api/v1/billing").json()
        assert (billing["plan_code"], billing["scheduled_plan_code"]) == ("studio", "starter")

        webhook(
            "subscription.charged",
            {
                "id": "sub_new1",
                "status": "active",
                "plan_id": "plan_starter",
                "current_end": 1893456000,
            },
        )
        sub = subscription(owner)
        assert (sub.plan.code, sub.scheduled_plan) == ("starter", None)

    def test_upgrading_again_before_renewal_drops_the_waiting_subscription_at_once(
        self, api, owner, fake_razorpay
    ):
        on_plan(owner, "studio", days_left=10)
        api.json("post", "/api/v1/billing/subscribe", {"plan": "starter"})
        approve(api)
        assert api.json("get", "/api/v1/billing/quote?plan=pro").json()["kind"] == "upgrade"
        api.json("post", "/api/v1/billing/subscribe", {"plan": "pro"})
        approve(api, "sub_new2", "pay_2")
        sub = subscription(owner)
        assert (sub.plan.code, sub.scheduled_plan) == ("pro", None)
        assert fake_razorpay["cancel"][-1] == ("sub_new1", False)


def test_cancelling_during_a_waiting_downgrade_stops_it_at_once(api, owner, fake_razorpay):
    on_plan(owner, "studio", days_left=10)
    api.json("post", "/api/v1/billing/subscribe", {"plan": "starter"})
    approve(api)
    assert api.json("post", "/api/v1/billing/cancel").json()["state"] == "ending"
    assert fake_razorpay["cancel"][-1] == ("sub_new1", False)
    sub = subscription(owner)
    assert (sub.plan.code, sub.scheduled_plan, sub.cancel_at_period_end) == ("studio", None, True)


class TestRefused:
    def test_same_plan(self, api, owner, fake_razorpay):
        on_plan(owner, "studio")
        response = api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})
        assert response.status_code == 400
        assert response.json()["detail"] == "You are already on the Studio plan."

    def test_while_a_payment_is_due(self, api, owner, fake_razorpay):
        on_plan(owner, "starter")
        with tenancy.bypass_rls():
            Subscription.objects.filter(studio=owner).update(status="past_due")
        assert api.json("get", "/api/v1/billing/quote?plan=studio").status_code == 400

    def test_keeping_a_cancelled_plan_starts_again_at_renewal_for_free(
        self, api, owner, fake_razorpay
    ):
        on_plan(owner, "studio", cancel_at_period_end=True)
        quote = api.json("get", "/api/v1/billing/quote?plan=studio").json()
        assert (quote["kind"], quote["charge_now_inr"]) == ("scheduled", 0)
        api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})
        approve(api)
        sub = subscription(owner)
        assert (sub.plan.code, sub.cancel_at_period_end, sub.scheduled_plan) == (
            "studio",
            False,
            None,
        )
        assert fake_razorpay["cancel"] == []  # already cancelled at period end
