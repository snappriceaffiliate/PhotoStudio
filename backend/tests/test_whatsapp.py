"""Sharing a gallery by WhatsApp: phone numbers, and clients without an email address."""

import pytest
from rest_framework import serializers

from apps.core.validators import whatsapp_number

from .conftest import PASSWORD
from .test_clients import make_event, outbox  # noqa: F401 - shared fixture

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "typed, stored",
    [
        ("98765 43210", "919876543210"),
        ("098765-43210", "919876543210"),
        ("+91 98765 43210", "919876543210"),
        ("0091 9876543210", "919876543210"),
        ("+44 7700 900123", "447700900123"),
        ("(+971) 50 123 4567", "971501234567"),
    ],
)
def test_phone_numbers_are_stored_with_country_code(typed, stored):
    assert whatsapp_number(typed) == stored


@pytest.mark.parametrize("typed", ["12345", "5876543210", "abc", "+0 123 456 789"])
def test_bad_phone_numbers_are_refused(typed):
    with pytest.raises(serializers.ValidationError):
        whatsapp_number(typed)


@pytest.fixture
def owner(api, make_studio):
    studio, user = make_studio("alpha")
    api.json("post", "/api/v1/auth/login", {"email": user.email, "password": PASSWORD})
    return studio


def share(api, event, **contact):
    return api.json(
        "post", f"/api/v1/events/{event.pk}/clients", {"client_name": "Priya Rao", **contact}
    )


def test_whatsapp_only_client_gets_a_login_and_no_email(api, owner, outbox):
    event = make_event(owner)
    response = share(api, event, phone="98765 43210")
    assert response.status_code == 201
    body = response.json()
    assert (body["phone"], body["email"]) == ("919876543210", "")
    assert body["password"]
    assert outbox == []


def test_email_and_phone_together_still_send_the_email(api, owner, outbox):
    event = make_event(owner)
    body = share(api, event, email="priya@example.com", phone="+91 98765 43210").json()
    assert body["phone"] == "919876543210"
    assert outbox[-1][0] == "priya@example.com"


def test_needs_an_email_or_a_phone(api, owner):
    event = make_event(owner)
    response = share(api, event)
    assert response.status_code == 400
    assert "WhatsApp" in response.json()["email"][0]


def test_new_password_for_whatsapp_only_client_sends_no_email(api, owner, outbox):
    event = make_event(owner)
    created = share(api, event, phone="9876543210").json()
    reset = api.json("post", f"/api/v1/client-access/{created['id']}/reset-password").json()
    assert reset["password"] != created["password"]
    assert outbox == []
