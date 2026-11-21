"""Studio branding: logo and accent colour, who may change them, and what clients see."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.accounts.models import User
from apps.billing.models import Plan, Subscription
from apps.core import storage, tenancy
from apps.studios.models import Studio
from apps.studios.views import contrast_with_white

from .conftest import PASSWORD
from .test_clients import make_event, outbox, shared  # noqa: F401 - shared fixtures

pytestmark = pytest.mark.django_db

WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 64


@pytest.fixture
def bucket(monkeypatch):
    objects: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put_object", lambda k, d, t: objects.__setitem__(k, d))
    monkeypatch.setattr(storage, "delete_object", lambda k: objects.pop(k, None))
    return objects


@pytest.fixture
def owner_api(api, make_studio):
    studio, owner = make_studio("lens")
    api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
    api.studio = studio
    return api


def upload(api, data=WEBP, name="logo.webp"):
    api.get("/api/v1/auth/csrf")
    return api.post(
        "/api/v1/studio/branding/logo",
        {"logo": SimpleUploadedFile(name, data, content_type="image/webp")},
        HTTP_X_CSRFTOKEN=api.cookies["csrftoken"].value,
    )


def test_contrast_rule():
    assert contrast_with_white("#0E5E5A") > 4.5
    assert contrast_with_white("#E89A1C") < 4.5


def test_owner_sets_and_resets_colour(owner_api):
    r = owner_api.json("patch", "/api/v1/studio/branding", {"accent_color": "#8a1c3b"})
    assert r.status_code == 200 and r.json()["accent_color"] == "#8A1C3B"
    r = owner_api.json("patch", "/api/v1/studio/branding", {"accent_color": ""})
    assert r.json()["accent_color"] is None


@pytest.mark.parametrize("colour", ["red", "#fff", "#FFD700", "#12345G"])
def test_bad_or_too_light_colours_are_refused(owner_api, colour):
    r = owner_api.json("patch", "/api/v1/studio/branding", {"accent_color": colour})
    assert r.status_code == 400 and "accent_color" in r.json()


def test_logo_upload_replaces_old_logo(owner_api, bucket):
    first = upload(owner_api)
    assert first.status_code == 201 and first.json()["logo_url"]
    old_key = Studio.objects.get(pk=owner_api.studio.pk).logo_key
    assert upload(owner_api).status_code == 201
    new_key = Studio.objects.get(pk=owner_api.studio.pk).logo_key
    assert new_key != old_key and list(bucket) == [new_key]
    assert new_key.startswith(f"studios/{owner_api.studio.pk}/logo/")


def test_logo_must_be_small_webp(owner_api, bucket):
    assert upload(owner_api, b"\x89PNG\r\n\x1a\n" + b"\x00" * 40).status_code == 400
    assert upload(owner_api, WEBP + b"\x00" * 70_000).status_code == 400
    assert bucket == {}


def test_logo_delete(owner_api, bucket):
    upload(owner_api)
    assert owner_api.json("delete", "/api/v1/studio/branding/logo").status_code == 204
    assert bucket == {} and Studio.objects.get(pk=owner_api.studio.pk).logo_key == ""


def test_staff_cannot_change_branding(api, make_studio):
    studio, _ = make_studio("lens")
    with tenancy.bypass_rls():
        User.objects.create_user(
            email="staff@lens.test",
            password=PASSWORD,
            full_name="Staff",
            studio=studio,
            role=User.Role.STAFF,
            email_verified_at=timezone.now(),
        )
    api.json("post", "/api/v1/auth/login", {"email": "staff@lens.test", "password": PASSWORD})
    r = api.json("patch", "/api/v1/studio/branding", {"accent_color": "#8A1C3B"})
    assert r.status_code == 403


def test_plan_without_branding_is_refused_and_hidden_from_clients(shared, api):
    studio = shared["studio"]
    Studio.objects.filter(pk=studio.pk).update(accent_color="#8A1C3B")
    assert shared["guest"].json("get", "/api/v1/client/me").json()["branding"] == {
        "logo_url": None,
        "accent_color": "#8A1C3B",
    }
    Plan.objects.filter(code="pro").update(custom_branding=False)
    r = api.json("patch", "/api/v1/studio/branding", {"accent_color": "#0E5E5A"})
    assert r.status_code == 402
    assert api.json("get", "/api/v1/studio/branding").json()["allowed"] is False
    assert shared["guest"].json("get", "/api/v1/client/me").json()["branding"] is None


def test_client_sees_no_branding_when_none_set(shared):
    assert shared["guest"].json("get", "/api/v1/client/me").json()["branding"] is None


def test_theme_is_for_studio_and_pro_plans_not_starter(api, make_studio):
    assert {p.code: p.custom_branding for p in Plan.objects.all()} == {
        "starter": False,
        "studio": True,
        "pro": True,
    }
    studio, owner = make_studio("lens")
    api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
    plans = {
        p["code"]: p["custom_theme"] for p in api.json("get", "/api/v1/billing").json()["plans"]
    }
    assert plans == {"starter": False, "studio": True, "pro": True}
    # A studio on Starter is told which plans include it.
    with tenancy.bypass_rls():
        Subscription.objects.filter(studio=studio).update(
            status=Subscription.Status.ACTIVE,
            plan=Plan.objects.get(code="starter"),
            current_period_end=timezone.now() + timedelta(days=20),
        )
    refused = api.json("patch", "/api/v1/studio/branding", {"accent_color": "#8A1C3B"})
    assert refused.status_code == 402
    assert "Studio or Pro" in refused.json()["detail"]
