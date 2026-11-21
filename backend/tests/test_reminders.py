"""Reminders for clients who have not submitted their selection."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.clients import tasks
from apps.clients.models import ClientAccess
from apps.core import tenancy
from apps.events.models import Event

from .conftest import PASSWORD
from .test_clients import make_event, outbox, photo_ids, shared  # noqa: F401 - shared fixtures

pytestmark = pytest.mark.django_db
URL = "/api/v1/reminders"


def shared_ago(days, hours=0):
    with tenancy.bypass_rls():
        ClientAccess.objects.update(created_at=timezone.now() - timedelta(days=days, hours=hours))


def reminded_ago(days):
    with tenancy.bypass_rls():
        ClientAccess.objects.update(last_reminded_at=timezone.now() - timedelta(days=days))


def due(api):
    return api.json("get", URL).json()


class TestWhoIsDue:
    def test_due_two_days_after_sharing_with_what_they_chose(self, api, shared):  # noqa: F811
        assert due(api)["count"] == 0
        shared_ago(1, 23)
        assert due(api)["count"] == 0
        guest = shared["guest"]
        guest.json("put", f"/api/v1/client/selections/{photo_ids(guest)[0]}")
        shared_ago(2)
        data = due(api)
        assert data["count"] == 1 and data["max_reminders"] == 3
        item = data["results"][0]
        assert item["client_name"] == "Priya Rao"
        assert item["reason"] == "first"
        assert item["selected"] == 1
        assert item["username"] == shared["creds"]["username"]
        assert item["event"]["title"] == "Wedding" and item["event"]["selection_limit"] == 3

    def test_then_every_three_days_at_most_three_times(self, api, shared):  # noqa: F811
        shared_ago(10)
        for n in range(1, 4):
            item = due(api)["results"][0]
            assert item["reason"] == ("first" if n == 1 else "again")
            sent = api.json("post", f"{URL}/{item['id']}/sent")
            assert sent.status_code == 200 and sent.json()["reminder_count"] == n
            assert due(api)["count"] == 0  # not again straight away
            reminded_ago(2)
            assert due(api)["count"] == 0
            reminded_ago(3)
        assert due(api)["count"] == 0  # three reminders sent: no more

    def test_the_day_before_the_gallery_expires(self, api, shared):  # noqa: F811
        tomorrow = timezone.localdate() + timedelta(days=1)
        with tenancy.bypass_rls():
            Event.objects.filter(pk=shared["event"].pk).update(expires_at=tomorrow)
        item = due(api)["results"][0]  # even though it was shared just now
        assert item["reason"] == "expiring"
        api.json("post", f"{URL}/{item['id']}/sent")
        assert due(api)["count"] == 0  # once only
        with tenancy.bypass_rls():
            Event.objects.filter(pk=shared["event"].pk).update(
                expires_at=timezone.localdate() - timedelta(days=1)
            )
        shared_ago(10)
        assert due(api)["count"] == 0  # expired galleries need no reminder

    def test_not_after_submitting_or_when_access_is_off(self, api, shared):  # noqa: F811
        shared_ago(5)
        guest = shared["guest"]
        guest.json("put", f"/api/v1/client/selections/{photo_ids(guest)[0]}")
        assert guest.json("post", "/api/v1/client/submit").status_code == 200
        assert due(api)["count"] == 0
        api.json("post", f"/api/v1/events/{shared['event'].pk}/reopen")
        assert due(api)["count"] == 1  # reopened: choosing again
        with tenancy.bypass_rls():
            ClientAccess.objects.update(is_active=False)
        assert due(api)["count"] == 0

    def test_studios_only_see_and_mark_their_own(self, api, shared, make_studio):  # noqa: F811
        shared_ago(5)
        item = due(api)["results"][0]
        api.json("post", "/api/v1/auth/logout")
        _, other_owner = make_studio("beta")
        api.json(
            "post",
            "/api/v1/auth/login",
            {"email": other_owner.email, "password": PASSWORD},
        )
        assert due(api)["count"] == 0
        assert api.json("post", f"{URL}/{item['id']}/sent").status_code == 404


class TestDailyEmail:
    def test_owner_is_emailed_once_per_reminder(self, shared, outbox):  # noqa: F811
        outbox.clear()
        assert tasks.remind_studios(timestamp=0) == 0
        shared_ago(2)
        assert tasks.remind_studios(timestamp=0) == 1
        to, subject, body = outbox[-1]
        assert to == shared["owner"].email
        assert subject == "1 client has not chosen their photos yet"
        assert "Priya Rao, Wedding" in body and "/reminders" in body
        assert tasks.remind_studios(timestamp=0) == 0  # not again the next morning
        with tenancy.bypass_rls():
            ClientAccess.objects.update(
                reminder_count=1, last_reminded_at=timezone.now() - timedelta(days=3)
            )
        assert tasks.remind_studios(timestamp=0) == 1  # due again: emailed again
