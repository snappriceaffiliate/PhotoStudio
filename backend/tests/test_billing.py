"""Trials, plan limits, lapsed accounts, Razorpay checkout verification and webhooks."""

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.billing import razorpay
from apps.billing.models import Plan, Subscription, WebhookEvent
from apps.core import tenancy
from apps.events.models import Event
from apps.notifications import emails

from .conftest import PASSWORD
from .test_clients import make_event

pytestmark = pytest.mark.django_db

KEY_SECRET = "test_key_secret"
WEBHOOK_SECRET = "test_webhook_secret"


@pytest.fixture(autouse=True)
def quiet_email(monkeypatch):
    monkeypatch.setattr(emails, "_queue", lambda *a: None)


@pytest.fixture
def razorpay_keys(settings):
    settings.RAZORPAY_KEY_ID = "rzp_test_123"
    settings.RAZORPAY_KEY_SECRET = KEY_SECRET
    settings.RAZORPAY_WEBHOOK_SECRET = WEBHOOK_SECRET
    with tenancy.bypass_rls():
        Plan.objects.filter(code="studio").update(razorpay_plan_id="plan_studio_1")


def set_subscription(studio, **fields):
    with tenancy.bypass_rls():
        Subscription.objects.filter(studio=studio).update(**fields)


def subscription(studio) -> Subscription:
    with tenancy.bypass_rls():
        return Subscription.objects.select_related("plan").get(studio=studio)


@pytest.fixture
def owner_on_trial(api, make_studio):
    studio, owner = make_studio("alpha")
    set_subscription(
        studio, status="trialing", plan=None, trial_ends_at=timezone.now() + timedelta(days=30)
    )
    api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
    return studio, owner


class TestTrial:
    def test_signup_starts_a_30_day_trial_shown_in_me(self, api):
        response = api.json(
            "post",
            "/api/v1/auth/signup",
            {
                "studio_name": "New",
                "full_name": "Asha",
                "email": "a@example.com",
                "password": PASSWORD,
            },
        )
        billing = response.json()["user"]["billing"]
        assert (billing["state"], billing["can_work"], billing["plan"]) == (
            "trial",
            True,
            "Free trial",
        )
        assert api.json("get", "/api/v1/auth/me").json()["user"]["billing"]["state"] == "trial"

    def test_trial_allows_one_active_event_until_one_is_archived(self, api, owner_on_trial):
        first = api.json("post", "/api/v1/events", {"title": "One"})
        assert first.status_code == 201
        second = api.json("post", "/api/v1/events", {"title": "Two"})
        assert second.status_code == 402
        assert "1 active event" in second.json()["detail"]
        api.json("post", f"/api/v1/events/{first.json()['id']}/archive")
        assert api.json("post", "/api/v1/events", {"title": "Two"}).status_code == 201

    def test_trial_staff_limit(self, api, owner_on_trial):
        assert (
            api.json("post", "/api/v1/staff", {"full_name": "A", "email": "a@x.com"}).status_code
            == 201
        )
        assert (
            api.json("post", "/api/v1/staff", {"full_name": "B", "email": "b@x.com"}).status_code
            == 402
        )

    def test_plan_photo_limit_applies_to_uploads(self, api, owner_on_trial):
        studio, _ = owner_on_trial
        pro = Plan.objects.get(code="pro")
        pro.max_photos_per_event = 2
        pro.save()
        set_subscription(studio, status="active", plan=pro)
        event = api.json("post", "/api/v1/events", {"title": "E"}).json()
        upload = api.json("post", f"/api/v1/events/{event['id']}/uploads").json()["id"]
        files = [{"relative_path": f"{i}.jpg"} for i in range(3)]
        assert (
            api.json("post", f"/api/v1/uploads/{upload}/files", {"files": files}).status_code == 400
        )


class TestLapsedAccount:
    def test_ended_trial_is_read_only_but_keeps_data_and_downloads(self, api, owner_on_trial):
        studio, _ = owner_on_trial
        event = make_event(studio, photos=2)
        set_subscription(studio, trial_ends_at=timezone.now() - timedelta(days=1))

        me = api.json("get", "/api/v1/auth/me").json()["user"]["billing"]
        assert (me["state"], me["can_work"]) == ("lapsed", False)
        assert api.json("post", "/api/v1/events", {"title": "X"}).status_code == 402
        assert api.json("post", f"/api/v1/events/{event.pk}/uploads").status_code == 402
        share = {"client_name": "C", "email": "c@x.com"}
        assert api.json("post", f"/api/v1/events/{event.pk}/clients", share).status_code == 402
        assert api.json("get", "/api/v1/events").status_code == 200
        assert api.json("get", f"/api/v1/events/{event.pk}/photos").status_code == 200

    def test_client_galleries_close_seven_days_after_lapse(self, api, make_studio):
        studio, owner = make_studio("alpha")
        event = make_event(studio)
        api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
        creds = api.json(
            "post", f"/api/v1/events/{event.pk}/clients", {"client_name": "C", "email": "c@x.com"}
        ).json()
        login = {"username": creds["username"], "password": creds["password"]}

        set_subscription(
            studio, status="cancelled", current_period_end=timezone.now() - timedelta(days=3)
        )
        assert (
            Client()
            .post("/api/v1/client/login", login, content_type="application/json")
            .status_code
            == 200
        )

        set_subscription(studio, current_period_end=timezone.now() - timedelta(days=8))
        refused = Client().post("/api/v1/client/login", login, content_type="application/json")
        assert refused.status_code == 403


class TestAccessRules:
    def make(self, **fields):
        return Subscription(**fields)

    def test_payment_due_keeps_working_for_the_grace_period(self):
        now = timezone.now()
        sub = self.make(status="past_due", past_due_since=now - timedelta(days=3))
        assert sub.access(now).state == "payment_due"
        assert sub.access(now + timedelta(days=5)).can_work is False

    def test_cancelled_plan_works_until_period_end(self):
        now = timezone.now()
        sub = self.make(status="cancelled", current_period_end=now + timedelta(days=10))
        assert sub.access(now).state == "ending"
        assert sub.access(now + timedelta(days=11)).state == "lapsed"


def sign(payment_id: str, subscription_id: str) -> str:
    return hmac.new(
        KEY_SECRET.encode(), f"{payment_id}|{subscription_id}".encode(), hashlib.sha256
    ).hexdigest()


class TestCheckout:
    def test_subscribe_creates_a_razorpay_subscription_for_the_owner(
        self, api, owner_on_trial, razorpay_keys, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(
            razorpay,
            "create_subscription",
            lambda plan_id, notes: calls.append(plan_id) or {"id": "sub_1", "status": "created"},
        )
        response = api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})
        assert response.status_code == 200
        assert (response.json()["subscription_id"], response.json()["key_id"]) == (
            "sub_1",
            "rzp_test_123",
        )
        assert calls == ["plan_studio_1"]
        sub = subscription(owner_on_trial[0])
        assert (sub.status, sub.pending_plan.code) == ("trialing", "studio")

    def test_plans_without_razorpay_ids_cannot_be_bought(self, api, owner_on_trial, razorpay_keys):
        assert api.json("post", "/api/v1/billing/subscribe", {"plan": "pro"}).status_code == 400

    def test_payment_signature_is_checked_against_the_stored_subscription(
        self, api, owner_on_trial, razorpay_keys, monkeypatch
    ):
        monkeypatch.setattr(
            razorpay, "create_subscription", lambda *a, **k: {"id": "sub_1", "status": "created"}
        )
        monkeypatch.setattr(
            razorpay,
            "fetch_subscription",
            lambda sid: {"status": "active", "current_end": 1893456000},
        )
        api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})

        forged = {
            "razorpay_payment_id": "pay_1",
            "razorpay_subscription_id": "sub_other",
            "razorpay_signature": sign("pay_1", "sub_other"),
        }
        assert api.json("post", "/api/v1/billing/verify", forged).status_code == 400

        good = {
            "razorpay_payment_id": "pay_1",
            "razorpay_subscription_id": "sub_1",
            "razorpay_signature": sign("pay_1", "sub_1"),
        }
        assert api.json("post", "/api/v1/billing/verify", good).json()["state"] == "active"
        sub = subscription(owner_on_trial[0])
        assert (sub.status, sub.plan.code, sub.current_period_end.year) == (
            "active",
            "studio",
            2030,
        )

    def test_staff_cannot_buy_or_cancel(self, api, owner_on_trial, razorpay_keys):
        studio, _ = owner_on_trial
        from apps.accounts.models import User

        User.objects.create_user(
            email="s@x.com", password=PASSWORD, full_name="S", studio=studio, role="staff"
        )
        api.json("post", "/api/v1/auth/logout")
        api.json("post", "/api/v1/auth/login", {"email": "s@x.com", "password": PASSWORD})
        assert api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"}).status_code == 403
        assert api.json("post", "/api/v1/billing/cancel").status_code == 403
        assert api.json("get", "/api/v1/billing").status_code == 200

    def test_cancel_asks_razorpay_to_stop_at_cycle_end(
        self, api, owner_on_trial, razorpay_keys, monkeypatch
    ):
        studio, _ = owner_on_trial
        set_subscription(
            studio,
            status="active",
            plan=Plan.objects.get(code="studio"),
            razorpay_subscription_id="sub_9",
            current_period_end=timezone.now() + timedelta(days=20),
        )
        calls = []
        monkeypatch.setattr(
            razorpay,
            "cancel_subscription",
            lambda sid, at_cycle_end: calls.append((sid, at_cycle_end)) or {},
        )
        assert api.json("post", "/api/v1/billing/cancel").json()["state"] == "ending"
        assert calls == [("sub_9", True)]


def webhook(event: str, entity: dict, event_id: str = "evt_1", secret: str = WEBHOOK_SECRET):
    body = json.dumps(
        {"event": event, "payload": {"subscription": {"entity": entity}}, "created_at": 1}
    ).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return Client().post(
        "/api/v1/billing/webhook",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=signature,
        HTTP_X_RAZORPAY_EVENT_ID=event_id,
    )


class TestWebhooks:
    @pytest.fixture
    def paying(self, make_studio, razorpay_keys):
        studio, _ = make_studio("alpha")
        set_subscription(
            studio,
            status="trialing",
            plan=None,
            razorpay_subscription_id="sub_1",
            pending_plan=Plan.objects.get(code="studio"),
        )
        return studio

    def test_rejects_a_bad_signature(self, paying):
        assert webhook("subscription.charged", {"id": "sub_1"}, secret="wrong").status_code == 400

    def test_charged_activates_the_plan_and_sets_the_period(self, paying):
        assert (
            webhook(
                "subscription.charged",
                {"id": "sub_1", "status": "active", "current_end": 1893456000},
            ).status_code
            == 200
        )
        sub = subscription(paying)
        assert (sub.status, sub.plan.code, sub.current_period_end.year) == (
            "active",
            "studio",
            2030,
        )

    def test_the_same_delivery_twice_is_applied_once(self, paying):
        webhook("subscription.halted", {"id": "sub_1", "status": "halted"}, event_id="evt_9")
        set_subscription(paying, status="active")
        webhook("subscription.halted", {"id": "sub_1", "status": "halted"}, event_id="evt_9")
        assert subscription(paying).status == "active"
        with tenancy.bypass_rls():
            assert WebhookEvent.objects.count() == 1

    def test_halted_payment_marks_payment_due_but_keeps_working(self, paying):
        webhook("subscription.halted", {"id": "sub_1", "status": "halted"})
        sub = subscription(paying)
        assert (sub.status, sub.access().state, sub.access().can_work) == (
            "past_due",
            "payment_due",
            True,
        )

    def test_cancelled_then_period_end(self, paying):
        webhook(
            "subscription.cancelled",
            {
                "id": "sub_1",
                "status": "cancelled",
                "current_end": int((timezone.now() + timedelta(days=5)).timestamp()),
            },
        )
        assert subscription(paying).access().state == "ending"

    def test_unknown_subscription_is_kept_for_support(self, paying):
        assert webhook("subscription.charged", {"id": "sub_unknown"}).status_code == 200
        with tenancy.bypass_rls():
            assert WebhookEvent.objects.get().processed is False


class TestBillingScreen:
    def test_shows_limits_usage_and_plans(self, api, owner_on_trial):
        api.json("post", "/api/v1/events", {"title": "One"})
        data = api.json("get", "/api/v1/billing").json()
        assert (
            data["state"],
            data["usage"]["active_events"],
            data["limits"]["max_active_events"],
        ) == ("trial", 1, 1)
        assert [p["code"] for p in data["plans"]] == ["starter", "studio", "pro"]
        assert data["payments_configured"] is False
        assert all(p["available"] is False for p in data["plans"])


def test_events_of_other_studios_do_not_count_toward_my_limit(api, owner_on_trial, make_studio):
    other, _ = make_studio("beta")
    make_event(other, title="Theirs")
    assert api.json("post", "/api/v1/events", {"title": "Mine"}).status_code == 201
    with tenancy.bypass_rls():
        assert Event.objects.count() == 2
