"""Sharing with a client, client login, selection rules and submission."""

import datetime

import pytest
from django.test import Client

from apps.clients.models import ClientAccess, Selection
from apps.core import tenancy
from apps.events.models import Event
from apps.notifications import emails
from apps.photos.models import Photo

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(
        emails, "_queue", lambda to, subject, body: sent.append((to, subject, body))
    )
    return sent


def make_event(studio, title="Wedding", photos=5, limit=3):
    with tenancy.bypass_rls():
        event = Event.objects.create(studio=studio, title=title, selection_limit=limit)
        for i in range(photos):
            Photo.objects.create(
                studio=studio,
                event=event,
                relative_path=f"{title}/{i:03}.jpg",
                original_filename=f"{i:03}.jpg",
                status=Photo.Status.READY,
                preview_key=f"k/{title}/{i}/p.webp",
                thumb_key=f"k/{title}/{i}/t.webp",
                sort_order=i,
            )
    return event


def client_api():
    c = Client(enforce_csrf_checks=True)

    def call(method, path, data=None):
        c.get("/api/v1/auth/csrf")
        token = c.cookies["csrftoken"].value
        body = {} if data is None and method in ("put", "post") else data
        return getattr(c, method)(
            path, body, content_type="application/json", HTTP_X_CSRFTOKEN=token
        )

    c.json = call
    return c


@pytest.fixture
def shared(api, make_studio, outbox):
    studio, owner = make_studio("alpha")
    event = make_event(studio)
    api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
    response = api.json(
        "post",
        f"/api/v1/events/{event.pk}/clients",
        {"client_name": "Priya Rao", "email": "Priya@Example.com"},
    )
    assert response.status_code == 201
    creds = response.json()
    guest = client_api()
    assert (
        guest.json(
            "post",
            "/api/v1/client/login",
            {"username": creds["username"], "password": creds["password"]},
        ).status_code
        == 200
    )
    return {"studio": studio, "owner": owner, "event": event, "creds": creds, "guest": guest}


def photo_ids(guest, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return [p["id"] for p in guest.json("get", f"/api/v1/client/photos?{query}").json()["results"]]


class TestSharing:
    def test_share_creates_login_emails_client_and_marks_event_shared(self, shared, outbox, api):
        creds = shared["creds"]
        assert (
            creds["username"].startswith("priya-") and len(creds["username"]) == len("priya-") + 6
        )
        assert len(creds["password"]) == 14
        to, subject, body = outbox[-1]
        assert to == "priya@example.com"
        assert creds["username"] in body and creds["password"] in body
        assert api.json("get", f"/api/v1/events/{shared['event'].pk}").json()["status"] == "shared"
        listed = api.json("get", f"/api/v1/events/{shared['event'].pk}/clients").json()
        assert "password" not in listed[0]
        with tenancy.bypass_rls():
            stored = ClientAccess.objects.get(username=creds["username"]).password_hash
        assert creds["password"] not in stored

    def test_cannot_share_an_event_without_photos(self, api, make_studio, outbox):
        studio, owner = make_studio("beta")
        event = make_event(studio, photos=0)
        api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
        response = api.json(
            "post",
            f"/api/v1/events/{event.pk}/clients",
            {"client_name": "X", "email": "x@example.com"},
        )
        assert response.status_code == 400

    def test_revoked_client_is_logged_out_and_reset_password_restores_access(self, shared, api):
        guest, access_id = shared["guest"], shared["creds"]["id"]
        assert api.json("post", f"/api/v1/client-access/{access_id}/revoke").status_code == 200
        assert guest.json("get", "/api/v1/client/me").status_code == 403
        new = api.json("post", f"/api/v1/client-access/{access_id}/reset-password").json()
        assert new["password"] != shared["creds"]["password"]
        old = guest.json(
            "post",
            "/api/v1/client/login",
            {"username": new["username"], "password": shared["creds"]["password"]},
        )
        assert old.status_code == 400
        assert (
            guest.json(
                "post",
                "/api/v1/client/login",
                {"username": new["username"], "password": new["password"]},
            ).status_code
            == 200
        )


class TestClientLogin:
    def test_locks_after_five_wrong_passwords_without_revealing_it(self, shared):
        guest = client_api()
        username = shared["creds"]["username"]
        wrong = [
            guest.json("post", "/api/v1/client/login", {"username": username, "password": "nope"})
            for _ in range(5)
        ]
        assert {r.status_code for r in wrong} == {400}
        locked = guest.json(
            "post",
            "/api/v1/client/login",
            {"username": username, "password": shared["creds"]["password"]},
        )
        unknown = guest.json(
            "post", "/api/v1/client/login", {"username": "nobody-zzzzzz", "password": "x"}
        )
        assert locked.status_code == unknown.status_code == 400
        assert locked.json() == unknown.json() == wrong[0].json()

    def test_expired_gallery_refuses_login(self, shared):
        with tenancy.bypass_rls():
            Event.objects.filter(pk=shared["event"].pk).update(expires_at=datetime.date(2020, 1, 1))
        guest = client_api()
        response = guest.json(
            "post",
            "/api/v1/client/login",
            shared["creds"] | {"password": shared["creds"]["password"]},
        )
        assert response.status_code == 403
        assert "expired" in response.json()["detail"]
        assert shared["guest"].json("get", "/api/v1/client/me").status_code == 403

    def test_studio_login_does_not_open_the_client_gallery(self, api, shared):
        assert api.json("get", "/api/v1/client/me").status_code == 403

    def test_me_describes_the_gallery(self, shared):
        me = shared["guest"].json("get", "/api/v1/client/me").json()
        assert (
            me["event"]["title"],
            me["event"]["selection_limit"],
            me["photo_count"],
            me["selected"],
        ) == ("Wedding", 3, 5, 0)


class TestSelection:
    def test_select_note_unselect_and_filter(self, shared):
        guest = shared["guest"]
        ids = photo_ids(guest)
        assert (
            guest.json(
                "put", f"/api/v1/client/selections/{ids[0]}", {"note": "Album cover"}
            ).json()["selected_count"]
            == 1
        )
        guest.json("put", f"/api/v1/client/selections/{ids[1]}")
        assert (
            guest.json("delete", f"/api/v1/client/selections/{ids[1]}").json()["selected_count"]
            == 1
        )
        chosen = guest.json("get", "/api/v1/client/photos?selected=1").json()["results"]
        assert [(p["id"], p["note"]) for p in chosen] == [(ids[0], "Album cover")]

    def test_selecting_twice_does_not_count_twice(self, shared):
        guest = shared["guest"]
        first = photo_ids(guest)[0]
        guest.json("put", f"/api/v1/client/selections/{first}")
        assert guest.json("put", f"/api/v1/client/selections/{first}").json()["selected_count"] == 1

    def test_limit_cannot_be_exceeded(self, shared):
        guest = shared["guest"]
        ids = photo_ids(guest)
        for photo in ids[:3]:
            assert guest.json("put", f"/api/v1/client/selections/{photo}").status_code == 200
        over = guest.json("put", f"/api/v1/client/selections/{ids[3]}")
        assert over.status_code == 409

    def test_submit_locks_the_selection_and_tells_the_studio(self, shared, api, outbox):
        guest = shared["guest"]
        ids = photo_ids(guest)
        assert (
            guest.json("post", "/api/v1/client/submit").status_code == 400
        )  # nothing selected yet
        guest.json("put", f"/api/v1/client/selections/{ids[0]}")
        submitted = guest.json("post", "/api/v1/client/submit")
        assert submitted.json()["photo_count"] == 1
        assert outbox[-1][0] == shared["owner"].email
        assert guest.json("put", f"/api/v1/client/selections/{ids[1]}").status_code == 409
        assert guest.json("delete", f"/api/v1/client/selections/{ids[0]}").status_code == 409
        progress = api.json("get", f"/api/v1/events/{shared['event'].pk}/progress").json()
        assert (progress["status"], progress["selected"]) == ("submitted", 1)
        assert progress["submitted_at"] is not None

        # The studio can reopen it for changes.
        assert api.json("post", f"/api/v1/events/{shared['event'].pk}/reopen").status_code == 200
        assert guest.json("put", f"/api/v1/client/selections/{ids[1]}").status_code == 200


class TestIsolation:
    def test_client_cannot_select_photos_from_another_event_or_studio(self, shared, make_studio):
        own_other_event = make_event(shared["studio"], title="Reception")
        studio_b, _ = make_studio("beta")
        foreign_event = make_event(studio_b, title="Foreign")
        with tenancy.bypass_rls():
            other_ids = [
                str(Photo.objects.filter(event=own_other_event).first().pk),
                str(Photo.objects.filter(event=foreign_event).first().pk),
            ]
        guest = shared["guest"]
        for photo in other_ids:
            assert guest.json("put", f"/api/v1/client/selections/{photo}").status_code == 404
        assert set(photo_ids(guest, page_size=200)).isdisjoint(other_ids)
        with tenancy.bypass_rls():
            assert Selection.objects.count() == 0

    def test_another_studio_cannot_see_or_manage_my_client(self, shared, api, make_studio):
        _, owner_b = make_studio("beta")
        api.json("post", "/api/v1/auth/logout")
        api.json("post", "/api/v1/auth/login", {"email": owner_b.email, "password": PASSWORD})
        assert api.json("get", f"/api/v1/events/{shared['event'].pk}/clients").status_code == 404
        assert (
            api.json(
                "post", f"/api/v1/client-access/{shared['creds']['id']}/reset-password"
            ).status_code
            == 404
        )

    def test_client_endpoints_need_csrf(self, shared):
        raw = Client(enforce_csrf_checks=True)
        response = raw.post(
            "/api/v1/client/login",
            {"username": shared["creds"]["username"], "password": shared["creds"]["password"]},
            content_type="application/json",
        )
        assert response.status_code == 403
