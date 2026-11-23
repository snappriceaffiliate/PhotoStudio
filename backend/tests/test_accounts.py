import re

import pytest
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.accounts.models import User
from apps.notifications import emails

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db

SIGNUP = {
    "studio_name": "Lens and Light",
    "full_name": "Asha Rao",
    "email": "Asha@Example.com",
    "password": PASSWORD,
    "phone": "98765 43210",
    "pincode": "600028",
    "password_confirm": PASSWORD,
}


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(
        emails, "_queue", lambda to, subject, body: sent.append((to, subject, body))
    )
    return sent


def link_params(body: str) -> dict:
    url = re.search(r"https?://\S+", body).group(0)
    return dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))


class TestSignup:
    def test_creates_studio_and_owner_and_logs_in(self, api, outbox):
        response = api.json("post", "/api/v1/auth/signup", SIGNUP)
        assert response.status_code == 201
        user = response.json()["user"]
        assert user["email"] == "asha@example.com"
        assert user["role"] == "owner"
        assert user["email_verified"] is False
        assert user["studio"]["slug"] == "lens-and-light"
        assert api.json("get", "/api/v1/auth/me").json()["user"]["email"] == "asha@example.com"
        assert outbox[0][0] == "asha@example.com"

    def test_saves_the_studio_phone_and_pincode(self, api, outbox):
        api.json("post", "/api/v1/auth/signup", SIGNUP)
        profile = api.json("get", "/api/v1/studio/profile").json()
        assert (profile["phone"], profile["pincode"]) == ("919876543210", "600028")

    def test_the_two_passwords_must_match(self, api, outbox):
        response = api.json("post", "/api/v1/auth/signup", {**SIGNUP, "password_confirm": "other"})
        assert response.status_code == 400
        assert response.json()["password_confirm"] == ["The passwords do not match."]

    def test_refuses_a_bad_pincode_or_phone(self, api, outbox):
        response = api.json(
            "post", "/api/v1/auth/signup", {**SIGNUP, "pincode": "12345", "phone": "123"}
        )
        assert response.status_code == 400
        assert {"pincode", "phone"} <= set(response.json())

    def test_queues_the_verification_email_as_a_background_job(
        self, api, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            api.json("post", "/api/v1/auth/signup", SIGNUP)
        job = ProcrastinateJob.objects.get(task_name="notifications.send_email")
        assert job.args["to"] == "asha@example.com"

    def test_second_studio_with_same_name_gets_unique_slug(self, api, outbox):
        api.json("post", "/api/v1/auth/signup", SIGNUP)
        api.post("/api/v1/auth/logout")
        other = api.json("post", "/api/v1/auth/signup", {**SIGNUP, "email": "b@example.com"})
        assert other.json()["user"]["studio"]["slug"] == "lens-and-light-2"

    def test_refuses_duplicate_email_and_weak_password(self, api, outbox):
        api.json("post", "/api/v1/auth/signup", SIGNUP)
        api.json("post", "/api/v1/auth/logout")
        assert "email" in api.json("post", "/api/v1/auth/signup", SIGNUP).json()
        weak = api.json(
            "post",
            "/api/v1/auth/signup",
            {
                **SIGNUP,
                "email": "c@example.com",
                "password": "12345678",
                "password_confirm": "12345678",
            },
        )
        assert weak.status_code == 400
        # Reported on the password field, so the form shows it next to that input.
        assert "password" in weak.json()

    def test_requires_csrf_token(self, outbox):
        from django.test import Client

        response = Client(enforce_csrf_checks=True).post(
            "/api/v1/auth/signup", SIGNUP, content_type="application/json"
        )
        assert response.status_code == 403


class TestLogin:
    def test_wrong_password_is_refused_and_right_one_logs_in(self, api, make_studio):
        _, owner = make_studio("alpha")
        bad = api.json(
            "post", "/api/v1/auth/login", {"email": owner.email, "password": "wrong-password"}
        )
        assert bad.status_code == 400
        ok = api.json(
            "post", "/api/v1/auth/login", {"email": owner.email.upper(), "password": PASSWORD}
        )
        assert ok.status_code == 200
        assert api.json("post", "/api/v1/auth/logout").status_code == 204
        assert api.json("get", "/api/v1/auth/me").json() == {"user": None}

    def test_is_rate_limited(self, api, make_studio):
        _, owner = make_studio("alpha")
        codes = [
            api.json(
                "post", "/api/v1/auth/login", {"email": owner.email, "password": "nope"}
            ).status_code
            for _ in range(21)
        ]
        assert codes[:20] == [400] * 20  # 20 tries per account per hour
        assert codes[20] == 429


class TestEmailVerification:
    def test_link_verifies_the_address(self, api, outbox):
        api.json("post", "/api/v1/auth/signup", SIGNUP)
        token = link_params(outbox[0][2])["token"]
        response = api.json("post", "/api/v1/auth/verify-email", {"token": token})
        assert response.json()["user"]["email_verified"] is True

    def test_tampered_token_is_refused(self, api, outbox):
        api.json("post", "/api/v1/auth/signup", SIGNUP)
        token = link_params(outbox[0][2])["token"]
        assert (
            api.json("post", "/api/v1/auth/verify-email", {"token": token + "x"}).status_code == 400
        )


class TestPasswordReset:
    def test_unknown_email_gets_the_same_answer_and_no_email(self, api, outbox):
        response = api.json("post", "/api/v1/auth/password-reset", {"email": "nobody@example.com"})
        assert response.status_code == 204
        assert outbox == []

    def test_link_sets_a_new_password_once(self, api, make_studio, outbox):
        _, owner = make_studio("alpha")
        api.json("post", "/api/v1/auth/password-reset", {"email": owner.email})
        params = link_params(outbox[0][2])
        new = {
            "uid": params["uid"],
            "token": params["token"],
            "password": "another-strong-pass-42",
            "password_confirm": "another-strong-pass-42",
        }
        assert api.json("post", "/api/v1/auth/password-set", new).status_code == 200
        owner.refresh_from_db()
        assert owner.check_password("another-strong-pass-42")
        # The token stops working once the password has changed.
        assert api.json("post", "/api/v1/auth/password-set", new).status_code == 400

    def test_the_two_new_passwords_must_match(self, api, make_studio, outbox):
        _, owner = make_studio("alpha")
        api.json("post", "/api/v1/auth/password-reset", {"email": owner.email})
        params = link_params(outbox[0][2])
        response = api.json(
            "post",
            "/api/v1/auth/password-set",
            {**params, "password": "another-strong-pass-42", "password_confirm": "another"},
        )
        assert response.status_code == 400
        assert response.json() == {"password_confirm": ["The passwords do not match."]}
        owner.refresh_from_db()
        assert owner.check_password(PASSWORD)  # unchanged, and the link still works


class TestStaff:
    def test_owner_invites_staff_who_sets_a_password(self, api, make_studio, outbox):
        studio, owner = make_studio("alpha")
        api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
        created = api.json(
            "post", "/api/v1/staff", {"full_name": "Ravi", "email": "ravi@example.com"}
        )
        assert created.status_code == 201
        assert created.json()["has_password"] is False
        staff = User.objects.get(email="ravi@example.com")
        assert (staff.studio_id, staff.role) == (studio.id, "staff")

        api.json("post", "/api/v1/auth/logout")
        params = link_params(outbox[-1][2])
        response = api.json(
            "post",
            "/api/v1/auth/password-set",
            {
                **params,
                "password": "ravi-strong-pass-77",
                "password_confirm": "ravi-strong-pass-77",
            },
        )
        assert response.json()["user"]["role"] == "staff"
        # Staff can work with events but cannot manage staff.
        assert api.json("get", "/api/v1/events").status_code == 200
        assert api.json("get", "/api/v1/staff").status_code == 403

    def test_removed_staff_lose_access_on_their_next_request(self, api, make_studio):
        studio, owner = make_studio("alpha")
        staff = User.objects.create_user(
            email="s@example.com", password=PASSWORD, full_name="S", studio=studio, role="staff"
        )
        from django.test import Client

        staff_client = Client()
        staff_client.post(
            "/api/v1/auth/login",
            {"email": staff.email, "password": PASSWORD},
            content_type="application/json",
        )
        assert staff_client.get("/api/v1/auth/me").json()["user"] is not None

        api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
        assert api.json("delete", f"/api/v1/staff/{staff.pk}").status_code == 204
        assert staff_client.get("/api/v1/auth/me").json()["user"] is None

    def test_owner_cannot_remove_the_owner_or_another_studios_staff(self, api, make_studio):
        _, owner_a = make_studio("alpha")
        studio_b, _ = make_studio("beta")
        other = User.objects.create_user(
            email="b-staff@example.com",
            password=PASSWORD,
            full_name="B",
            studio=studio_b,
            role="staff",
        )
        api.json("post", "/api/v1/auth/login", {"email": owner_a.email, "password": PASSWORD})
        assert api.json("delete", f"/api/v1/staff/{owner_a.pk}").status_code == 400
        assert api.json("delete", f"/api/v1/staff/{other.pk}").status_code == 404
