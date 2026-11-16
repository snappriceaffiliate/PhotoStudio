"""The defaults until an email service is set up: share by WhatsApp only, without the studio
having to confirm its email first (CLIENT_EMAIL_SHARING and REQUIRE_VERIFIED_EMAIL_TO_SHARE off)."""

import pytest

from apps.accounts.models import User
from apps.clients.models import ClientAccess
from apps.core import tenancy

from .conftest import PASSWORD
from .test_clients import make_event, outbox  # noqa: F401 - shared fixture

pytestmark = pytest.mark.django_db


@pytest.fixture
def whatsapp_only(settings):
    settings.CLIENT_EMAIL_SHARING = False
    settings.REQUIRE_VERIFIED_EMAIL_TO_SHARE = False


@pytest.fixture
def unconfirmed_owner(api, make_studio, whatsapp_only):
    studio, owner = make_studio("alpha")
    with tenancy.bypass_rls():
        User.objects.filter(pk=owner.pk).update(email_verified_at=None)
    api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
    return studio, make_event(studio)


def share(api, event, **body):
    return api.json(
        "post", f"/api/v1/events/{event.pk}/clients", {"client_name": "Priya Rao", **body}
    )


def test_a_studio_that_has_not_confirmed_its_email_can_share_by_whatsapp(
    api, unconfirmed_owner, outbox
):
    _, event = unconfirmed_owner
    response = share(api, event, phone="98765 43210")
    assert response.status_code == 201
    assert response.json()["phone"] == "919876543210"
    assert response.json()["password"]
    assert outbox == []  # nothing is emailed
    assert api.json("get", f"/api/v1/events/{event.pk}").json()["status"] == "shared"


def test_a_whatsapp_number_is_required(api, unconfirmed_owner):
    _, event = unconfirmed_owner
    for body in ({}, {"email": "priya@example.com"}):
        response = share(api, event, **body)
        assert response.status_code == 400
        assert response.json()["phone"] == ["Enter the client's WhatsApp number."]


def test_an_email_sent_anyway_is_neither_kept_nor_used(api, unconfirmed_owner, outbox):
    _, event = unconfirmed_owner
    response = share(api, event, phone="98765 43210", email="priya@example.com")
    assert response.status_code == 201
    assert response.json()["email"] == ""
    assert outbox == []


def test_a_new_password_is_not_emailed_either(api, unconfirmed_owner, outbox):
    studio, event = unconfirmed_owner
    created = share(api, event, phone="98765 43210").json()
    with tenancy.bypass_rls():  # an older login that still has an email address
        ClientAccess.objects.filter(pk=created["id"]).update(email="priya@example.com")
    response = api.json("post", f"/api/v1/client-access/{created['id']}/reset-password")
    assert response.status_code == 200 and response.json()["password"]
    assert outbox == []


def test_the_screens_are_told_how_sharing_works(api, unconfirmed_owner):
    sharing = api.json("get", "/api/v1/auth/me").json()["user"]["sharing"]
    assert sharing == {"client_email": False, "confirm_email_first": False}


def test_inviting_staff_still_needs_a_confirmed_email(api, unconfirmed_owner):
    # A staff invitation can only arrive by email, so this check stays.
    response = api.json("post", "/api/v1/staff", {"full_name": "Ravi", "email": "ravi@example.com"})
    assert response.status_code == 403
