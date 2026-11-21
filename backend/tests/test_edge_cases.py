"""Refusals and odd inputs across the client gallery, events and accounts."""

import pytest
from django.core import mail

from apps.accounts.models import User
from apps.core import tenancy

from .conftest import PASSWORD
from .test_accounts import link_params
from .test_clients import outbox, photo_ids, shared  # noqa: F401 - shared fixtures

pytestmark = pytest.mark.django_db

ME = "/api/v1/client/me"


class TestClientGallery:
    def test_logout_ends_the_session(self, shared):
        guest = shared["guest"]
        assert guest.json("get", ME).status_code == 200
        assert guest.json("post", "/api/v1/client/logout").status_code == 204
        assert guest.json("get", ME).status_code == 403

    def test_logout_without_a_session_is_harmless(self, client):
        assert client.post("/api/v1/client/logout").status_code in (204, 403)

    @pytest.mark.parametrize("query", ["page=abc", "page_size=lots", "page=1.5"])
    def test_page_numbers_must_be_numbers(self, shared, query):
        response = shared["guest"].json("get", f"/api/v1/client/photos?{query}")
        assert response.status_code == 400

    def test_album_filter_must_be_an_album_id(self, shared):
        response = shared["guest"].json("get", "/api/v1/client/photos?album=not-a-uuid")
        assert response.status_code == 400
        assert "album" in response.json()["detail"]

    def test_page_size_is_capped_and_page_zero_means_page_one(self, shared):
        data = shared["guest"].json("get", "/api/v1/client/photos?page=0&page_size=99999").json()
        assert data["count"] == 5 and len(data["results"]) == 5

    def test_a_second_submit_is_refused(self, shared):
        guest = shared["guest"]
        guest.json("put", f"/api/v1/client/selections/{photo_ids(guest)[0]}")
        assert guest.json("post", "/api/v1/client/submit").status_code == 200
        assert guest.json("post", "/api/v1/client/submit").status_code == 409

    def test_selecting_a_photo_of_another_event_is_a_404(self, shared):
        import uuid

        response = shared["guest"].json("put", f"/api/v1/client/selections/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_no_login_means_no_gallery(self, client):
        assert client.get(ME).status_code == 403
        assert client.get("/api/v1/client/photos").status_code == 403


class TestStudioActions:
    def test_cannot_reopen_a_selection_that_was_never_submitted(self, api, shared):
        response = api.json("post", f"/api/v1/events/{shared['event'].pk}/reopen")
        assert response.status_code == 400
        assert "not submitted" in response.json()["detail"]

    def test_cannot_share_an_archived_event(self, api, shared):
        event = shared["event"]
        api.json("post", f"/api/v1/events/{event.pk}/archive")
        response = api.json(
            "post",
            f"/api/v1/events/{event.pk}/clients",
            {"client_name": "Late Client", "email": "late@example.com"},
        )
        assert response.status_code == 400
        assert "archived" in response.json()["detail"]

    def test_archiving_twice_is_harmless_and_unarchive_needs_an_archived_event(self, api, shared):
        event = shared["event"]
        url = f"/api/v1/events/{event.pk}"
        assert api.json("post", f"{url}/unarchive").status_code == 400  # not archived yet
        assert api.json("post", f"{url}/archive").status_code == 200
        assert api.json("post", f"{url}/archive").status_code == 200

    def test_unknown_actions_are_404s(self, api, shared):
        event = shared["event"]
        assert api.json("post", f"/api/v1/events/{event.pk}/explode").status_code == 404
        listed = api.json("get", f"/api/v1/events/{event.pk}/clients").json()
        assert (
            api.json("post", f"/api/v1/client-access/{listed[0]['id']}/delete").status_code == 404
        )

    def test_sharing_needs_an_email_or_a_whatsapp_number(self, api, shared):
        response = api.json(
            "post", f"/api/v1/events/{shared['event'].pk}/clients", {"client_name": "No Contact"}
        )
        assert response.status_code == 400


class TestAccountEdges:
    def test_resend_verification_only_for_unverified_studio_users(self, api, make_studio, outbox):
        studio, owner = make_studio("alpha")
        api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
        assert api.json("post", "/api/v1/auth/resend-verification").status_code == 204
        assert outbox == []  # already verified: nothing to send

        with tenancy.bypass_rls():
            User.objects.filter(pk=owner.pk).update(email_verified_at=None)
        assert api.json("post", "/api/v1/auth/resend-verification").status_code == 204
        assert len(outbox) == 1 and outbox[0][0] == owner.email

    def test_resend_verification_needs_a_login(self, api):
        assert api.json("post", "/api/v1/auth/resend-verification").status_code in (401, 403)

    def test_weak_new_passwords_are_refused_and_the_link_stays_usable(
        self, api, make_studio, outbox
    ):
        _, owner = make_studio("alpha")
        api.json("post", "/api/v1/auth/password-reset", {"email": owner.email})
        params = link_params(outbox[0][2])

        weak = api.json("post", "/api/v1/auth/password-set", {**params, "password": "12345678"})
        assert weak.status_code == 400 and weak.json()["password"]
        owner.refresh_from_db()
        assert owner.check_password(PASSWORD)  # unchanged

        strong = {**params, "password": "a-much-better-pass-73"}
        assert api.json("post", "/api/v1/auth/password-set", strong).status_code == 200

    def test_a_tampered_link_is_refused(self, api, make_studio, outbox):
        _, owner = make_studio("alpha")
        api.json("post", "/api/v1/auth/password-reset", {"email": owner.email})
        params = link_params(outbox[0][2])
        forged = {**params, "token": params["token"][:-3] + "abc", "password": "a-strong-pass-12"}
        response = api.json("post", "/api/v1/auth/password-set", forged)
        assert response.status_code == 400
        assert "invalid or has expired" in response.json()["detail"]

    def test_the_owner_sees_the_whole_team_and_only_their_studio(self, api, make_studio):
        studio, owner = make_studio("alpha")
        with tenancy.bypass_rls():
            User.objects.create_user(
                email="staff@alpha.test",
                password=PASSWORD,
                full_name="Zed Staff",
                studio=studio,
                role=User.Role.STAFF,
            )
        api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
        other, _ = make_studio("beta")
        team = api.json("get", "/api/v1/staff").json()
        assert sorted(m["email"] for m in team) == [owner.email, "staff@alpha.test"]
        assert other.slug == "beta"  # its owner exists but is not listed

    def test_signup_with_a_taken_email_is_refused(self, api, make_studio):
        _, owner = make_studio("alpha")
        response = api.json(
            "post",
            "/api/v1/auth/signup",
            {
                "studio_name": "Another",
                "full_name": "Someone",
                "email": owner.email.upper(),
                "password": PASSWORD,
                "phone": "98765 43210",
                "pincode": "600028",
                "password_confirm": PASSWORD,
            },
        )
        assert response.status_code == 400 and "email" in response.json()

    def test_signup_validates_every_field(self, api):
        response = api.json("post", "/api/v1/auth/signup", {})
        assert response.status_code == 400
        assert {
            "studio_name",
            "full_name",
            "email",
            "phone",
            "pincode",
            "password",
            "password_confirm",
        } <= set(response.json())

    def test_logout_ends_the_studio_session(self, api, make_studio):
        _, owner = make_studio("alpha")
        api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
        assert api.json("get", "/api/v1/events").status_code == 200
        api.json("post", "/api/v1/auth/logout")
        assert api.json("get", "/api/v1/events").status_code in (401, 403)

    def test_login_failures_do_not_reveal_which_part_was_wrong(self, api, make_studio):
        _, owner = make_studio("alpha")
        wrong_password = api.json(
            "post", "/api/v1/auth/login", {"email": owner.email, "password": "wrong-pass-1"}
        )
        unknown_email = api.json(
            "post", "/api/v1/auth/login", {"email": "nobody@x.test", "password": "wrong-pass-1"}
        )
        assert wrong_password.status_code == unknown_email.status_code == 400
        assert wrong_password.json() == unknown_email.json()
        assert mail.outbox == []


class TestEventInput:
    @pytest.fixture
    def owner_api(self, api, make_studio):
        _, owner = make_studio("alpha")
        api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
        return api

    @pytest.mark.parametrize("title", ["", "   "])
    def test_an_event_needs_a_name(self, owner_api, title):
        response = owner_api.json("post", "/api/v1/events", {"title": title})
        assert response.status_code == 400 and "title" in response.json()

    def test_a_limit_must_be_a_positive_number(self, owner_api):
        for bad in (0, -5, "many"):
            response = owner_api.json(
                "post", "/api/v1/events", {"title": "Wedding", "selection_limit": bad}
            )
            assert response.status_code == 400, bad
        ok = owner_api.json("post", "/api/v1/events", {"title": "Wedding", "selection_limit": 50})
        assert ok.status_code == 201 and ok.json()["selection_limit"] == 50

    def test_no_limit_is_allowed(self, owner_api):
        response = owner_api.json("post", "/api/v1/events", {"title": "Wedding"})
        assert response.status_code == 201 and response.json()["selection_limit"] is None
