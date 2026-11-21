"""The studio profile, the person's own name, and changing the password."""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEntry
from apps.core import tenancy
from apps.studios.models import Studio

from .conftest import PASSWORD
from .test_clients import make_event, outbox, photo_ids, shared  # noqa: F401 - shared fixtures
from .test_uploads import studio_a  # noqa: F401 - shared fixture

pytestmark = pytest.mark.django_db
URL = "/api/v1/studio/profile"


class TestStudioProfile:
    def test_the_owner_fills_in_the_profile(self, api, studio_a):  # noqa: F811
        response = api.json(
            "patch",
            URL,
            {
                "name": "  Lens and Light  ",
                "phone": "98765 43210",
                "contact_email": "hello@lens.test",
                "address": "12 MG Road",
                "city": "Chennai",
                "pincode": "600 028",
                "website": "lensandlight.in",
                "instagram": "https://www.instagram.com/lens.and_light/",
            },
        )
        assert response.status_code == 200
        assert response.json() == {
            "name": "Lens and Light",
            "phone": "919876543210",
            "contact_email": "hello@lens.test",
            "address": "12 MG Road",
            "city": "Chennai",
            "pincode": "600028",
            "website": "https://lensandlight.in",
            "instagram": "lens.and_light",
        }
        assert api.json("get", URL).json()["city"] == "Chennai"
        # The new name is what the top bar shows.
        assert (
            api.json("get", "/api/v1/auth/me").json()["user"]["studio"]["name"] == "Lens and Light"
        )
        with tenancy.bypass_rls():
            entry = AuditEntry.objects.get(action="studio.profile")
        assert "name" in entry.detail and "city" in entry.detail

    @pytest.mark.parametrize(
        "field, value, message",
        [
            ("name", "   ", "studio's name"),
            ("phone", "12345", "10-digit"),
            ("contact_email", "not-an-email", "email"),
            ("website", "not a site", "URL"),
            ("instagram", "has spaces here", "Instagram handle"),
            ("address", "line one\nline two", "one line"),
        ],
    )
    def test_explains_wrong_values(self, api, studio_a, field, value, message):  # noqa: F811
        response = api.json("patch", URL, {field: value})
        assert response.status_code == 400
        assert message in " ".join(response.json()[field])

    def test_fields_can_be_cleared(self, api, studio_a):  # noqa: F811
        api.json("patch", URL, {"phone": "9876543210", "instagram": "@lens"})
        response = api.json("patch", URL, {"phone": "", "instagram": ""})
        assert (response.json()["phone"], response.json()["instagram"]) == ("", "")

    def test_staff_can_read_but_not_change_it(self, api, studio_a):  # noqa: F811
        with tenancy.bypass_rls():
            User.objects.create_user(
                email="staff@alpha.test",
                password=PASSWORD,
                full_name="Staff",
                studio=studio_a["studio"],
                role=User.Role.STAFF,
                email_verified_at=timezone.now(),
            )
        api.json("post", "/api/v1/auth/logout")
        api.json("post", "/api/v1/auth/login", {"email": "staff@alpha.test", "password": PASSWORD})
        assert api.json("get", URL).status_code == 200
        refused = api.json("patch", URL, {"name": "Mine now"})
        assert refused.status_code == 403
        assert Studio.objects.get(pk=studio_a["studio"].pk).name != "Mine now"

    def test_needs_a_studio_login(self, api):
        assert api.json("get", URL).status_code == 403

    def test_each_studio_only_changes_its_own(self, api, studio_a, make_studio):  # noqa: F811
        other, _ = make_studio("beta")
        api.json("patch", URL, {"city": "Madurai"})
        with tenancy.bypass_rls():
            assert Studio.objects.get(pk=other.pk).city == ""


class TestGalleryContact:
    def test_clients_see_how_to_reach_the_studio(self, api, shared):  # noqa: F811
        guest = shared["guest"]
        assert guest.json("get", "/api/v1/client/me").json()["studio_contact"] is None
        api.json(
            "patch", URL, {"phone": "9876543210", "instagram": "lens", "address": "12 MG Road"}
        )
        contact = guest.json("get", "/api/v1/client/me").json()["studio_contact"]
        assert contact == {
            "phone": "919876543210",
            "email": None,
            "city": None,
            "website": None,
            "instagram": "lens",
        }  # the street address stays private


class TestAccount:
    def test_changes_own_name(self, api, studio_a):  # noqa: F811
        response = api.json("patch", "/api/v1/auth/account", {"full_name": " Priya R "})
        assert response.status_code == 200
        assert response.json()["user"]["full_name"] == "Priya R"
        assert api.json("patch", "/api/v1/auth/account", {"full_name": ""}).status_code == 400

    def test_changes_password_and_stays_logged_in(self, api, studio_a):  # noqa: F811
        owner = studio_a["owner"]
        wrong = api.json(
            "post",
            "/api/v1/auth/password-change",
            {"current_password": "nope", "new_password": "a-new-strong-pass-77"},
        )
        assert wrong.status_code == 400 and "current_password" in wrong.json()
        weak = api.json(
            "post",
            "/api/v1/auth/password-change",
            {"current_password": PASSWORD, "new_password": "123"},
        )
        assert weak.status_code == 400 and "new_password" in weak.json()
        ok = api.json(
            "post",
            "/api/v1/auth/password-change",
            {"current_password": PASSWORD, "new_password": "a-new-strong-pass-77"},
        )
        assert ok.status_code == 200
        assert api.json("get", URL).status_code == 200  # this session still works
        owner.refresh_from_db()
        assert owner.check_password("a-new-strong-pass-77")

    def test_needs_a_login(self, api):
        response = api.json(
            "post",
            "/api/v1/auth/password-change",
            {"current_password": "x", "new_password": "y"},
        )
        assert response.status_code == 403
