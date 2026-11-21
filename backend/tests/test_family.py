"""Family helpers: relatives with their own login who help choose but cannot submit."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.clients.models import ClientAccess
from apps.core import tenancy

from .test_clients import (  # noqa: F401 - shared fixtures
    client_api,
    make_event,
    outbox,
    photo_ids,
    shared,
)

pytestmark = pytest.mark.django_db


def invite(guest, name="Ravi Uncle", phone="98765 43210"):
    return guest.json("post", "/api/v1/client/family", {"client_name": name, "phone": phone})


def log_in(creds):
    helper = client_api()
    response = helper.json(
        "post",
        "/api/v1/client/login",
        {"username": creds["username"], "password": creds["password"]},
    )
    assert response.status_code == 200
    return helper


@pytest.fixture
def family(shared):  # noqa: F811
    response = invite(shared["guest"])
    assert response.status_code == 201
    creds = response.json()
    return {**shared, "helper_creds": creds, "helper": log_in(creds)}


class TestInviting:
    def test_the_main_client_invites_a_relative_with_their_own_login(self, family):
        creds = family["helper_creds"]
        assert creds["client_name"] == "Ravi Uncle"
        assert creds["phone"] == "919876543210"
        assert creds["username"].startswith("ravi-") and len(creds["password"]) == 14
        me = family["helper"].json("get", "/api/v1/client/me").json()
        assert (me["role"], me["main_name"]) == ("helper", "Priya Rao")
        main = family["guest"].json("get", "/api/v1/client/me").json()
        assert (main["role"], main["main_name"]) == ("main", "Priya Rao")
        with tenancy.bypass_rls():
            helper = ClientAccess.objects.select_related("invited_by").get(
                username=creds["username"]
            )
        assert helper.invited_by.client_name == "Priya Rao"

    def test_helpers_cannot_invite_or_see_the_family(self, family):
        helper = family["helper"]
        assert invite(helper, "Cousin").status_code == 403
        refused = helper.json("get", "/api/v1/client/family")
        assert refused.status_code == 403 and "Priya Rao" in refused.json()["detail"]

    def test_at_most_ten_helpers(self, family):
        for n in range(9):
            assert invite(family["guest"], f"Relative {n}", "").status_code == 201
        full = invite(family["guest"], "One too many", "")
        assert full.status_code == 400 and "10" in full.json()["detail"]

    def test_the_main_client_sees_who_chose_how_many_and_can_turn_off_a_helper(self, family):
        guest, helper = family["guest"], family["helper"]
        ids = photo_ids(guest)
        guest.json("put", f"/api/v1/client/selections/{ids[0]}")
        helper.json("put", f"/api/v1/client/selections/{ids[1]}")
        data = guest.json("get", "/api/v1/client/family").json()
        assert data["you"] == {"client_name": "Priya Rao", "chosen": 1}
        assert [(h["client_name"], h["chosen"]) for h in data["helpers"]] == [("Ravi Uncle", 1)]
        helper_id = data["helpers"][0]["id"]
        assert guest.json("post", f"/api/v1/client/family/{helper_id}/turn-off").status_code == 204
        assert helper.json("get", "/api/v1/client/me").status_code == 403  # logged out


class TestChoosing:
    def test_helpers_choose_and_everyone_sees_who_chose_what(self, family):
        guest, helper = family["guest"], family["helper"]
        ids = photo_ids(guest)
        guest.json("put", f"/api/v1/client/selections/{ids[0]}")
        assert helper.json("put", f"/api/v1/client/selections/{ids[1]}").status_code == 200
        photos = {p["id"]: p for p in guest.json("get", "/api/v1/client/photos").json()["results"]}
        assert (photos[ids[0]]["chosen_by"], photos[ids[0]]["chosen_by_me"]) == ("Priya Rao", True)
        assert (photos[ids[1]]["chosen_by"], photos[ids[1]]["chosen_by_me"]) == (
            "Ravi Uncle",
            False,
        )
        assert photos[ids[2]]["chosen_by"] is None

    def test_helpers_change_only_their_own_picks_the_main_client_any(self, family):
        guest, helper = family["guest"], family["helper"]
        ids = photo_ids(guest)
        guest.json("put", f"/api/v1/client/selections/{ids[0]}")
        helper.json("put", f"/api/v1/client/selections/{ids[1]}")
        refused = helper.json("delete", f"/api/v1/client/selections/{ids[0]}")
        assert refused.status_code == 403
        assert "Priya Rao chose this photo" in refused.json()["detail"]
        note = helper.json("put", f"/api/v1/client/selections/{ids[0]}", {"note": "crop"})
        assert note.status_code == 403
        assert helper.json("delete", f"/api/v1/client/selections/{ids[1]}").status_code == 200
        helper.json("put", f"/api/v1/client/selections/{ids[1]}")
        assert guest.json("delete", f"/api/v1/client/selections/{ids[1]}").status_code == 200

    def test_the_photo_limit_is_shared(self, family):
        guest, helper = family["guest"], family["helper"]
        ids = photo_ids(guest)  # the event allows 3
        guest.json("put", f"/api/v1/client/selections/{ids[0]}")
        helper.json("put", f"/api/v1/client/selections/{ids[1]}")
        helper.json("put", f"/api/v1/client/selections/{ids[2]}")
        assert guest.json("put", f"/api/v1/client/selections/{ids[3]}").status_code == 409


class TestSubmitting:
    def test_only_the_main_client_submits(self, family, api):
        guest, helper = family["guest"], family["helper"]
        ids = photo_ids(guest)
        helper.json("put", f"/api/v1/client/selections/{ids[0]}")
        refused = helper.json("post", "/api/v1/client/submit")
        assert refused.status_code == 403
        assert refused.json()["detail"] == "Only Priya Rao can submit the final selection."
        assert guest.json("post", "/api/v1/client/submit").status_code == 200
        selection = api.json("get", f"/api/v1/events/{family['event'].pk}/selection").json()
        assert [r["chosen_by"] for r in selection["results"]] == ["Ravi Uncle"]
        assert invite(guest, "Late cousin").status_code == 409


class TestStudio:
    def test_the_studio_adds_a_family_member_to_the_main_client(self, shared, api):  # noqa: F811
        url = f"/api/v1/events/{shared['event'].pk}/clients"
        added = api.json(
            "post",
            url,
            {"client_name": "Anu", "email": "anu@example.com", "role": "helper"},
        )
        assert added.status_code == 201
        assert (added.json()["role"], added.json()["invited_by"]) == ("helper", "Priya Rao")
        listed = {c["client_name"]: c["role"] for c in api.json("get", url).json()}
        assert listed == {"Priya Rao": "main", "Anu": "helper"}

    def test_a_family_member_needs_a_main_client_first(self, api, make_studio):
        from .conftest import PASSWORD

        studio, owner = make_studio("solo")
        event = make_event(studio, title="Solo")
        api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
        refused = api.json(
            "post",
            f"/api/v1/events/{event.pk}/clients",
            {"client_name": "Anu", "email": "anu@example.com", "role": "helper"},
        )
        assert refused.status_code == 400 and "main client first" in refused.json()["detail"]

    def test_reminders_go_only_to_the_main_client(self, family, api):
        with tenancy.bypass_rls():
            ClientAccess.objects.update(created_at=timezone.now() - timedelta(days=3))
        names = [r["client_name"] for r in api.json("get", "/api/v1/reminders").json()["results"]]
        assert names == ["Priya Rao"]
