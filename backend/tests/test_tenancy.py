"""Tenant isolation: one studio must never see or change another studio's data.

Covers both layers: PostgreSQL row-level security on its own (no Django filter),
and the API, which also scopes every query by studio.
"""

import pytest
from django.db import DatabaseError, transaction

from apps.core import tenancy
from apps.events.models import Event

from .conftest import PASSWORD, is_superuser_connection

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_studios(make_studio):
    (a, owner_a), (b, owner_b) = make_studio("alpha"), make_studio("beta")
    with tenancy.bypass_rls():
        event_a = Event.objects.create(studio=a, title="Alpha wedding")
        event_b = Event.objects.create(studio=b, title="Beta wedding")
    return {
        "a": a,
        "b": b,
        "owner_a": owner_a,
        "owner_b": owner_b,
        "event_a": event_a,
        "event_b": event_b,
    }


def test_app_role_is_not_a_superuser():
    # Superusers skip row-level security, which would make every test below meaningless.
    assert not is_superuser_connection()


class TestRowLevelSecurity:
    def test_shows_only_the_current_studios_rows_without_any_filter(self, two_studios):
        with tenancy.studio_context(two_studios["a"].id):
            assert list(Event.objects.values_list("title", flat=True)) == ["Alpha wedding"]

    def test_shows_nothing_when_no_studio_is_set(self, two_studios):
        assert Event.objects.count() == 0

    def test_refuses_to_write_a_row_into_another_studio(self, two_studios):
        with tenancy.studio_context(two_studios["a"].id), pytest.raises(DatabaseError):
            with transaction.atomic():
                Event.objects.create(studio=two_studios["b"], title="Sneaky")

    def test_cannot_update_another_studios_row(self, two_studios):
        with tenancy.studio_context(two_studios["a"].id):
            changed = Event.objects.filter(pk=two_studios["event_b"].pk).update(title="Hacked")
        assert changed == 0

    def test_bypass_is_needed_to_see_every_studio(self, two_studios):
        with tenancy.bypass_rls():
            assert Event.objects.count() == 2


class TestEventApi:
    def login(self, api, email):
        assert (
            api.json(
                "post", "/api/v1/auth/login", {"email": email, "password": PASSWORD}
            ).status_code
            == 200
        )

    def test_lists_only_own_events(self, api, two_studios):
        self.login(api, two_studios["owner_a"].email)
        titles = [e["title"] for e in api.json("get", "/api/v1/events").json()]
        assert titles == ["Alpha wedding"]

    @pytest.mark.parametrize("method", ["get", "patch"])
    def test_another_studios_event_is_not_found(self, api, two_studios, method):
        self.login(api, two_studios["owner_a"].email)
        response = api.json(method, f"/api/v1/events/{two_studios['event_b'].pk}", {"title": "x"})
        assert response.status_code == 404
        with tenancy.bypass_rls():
            two_studios["event_b"].refresh_from_db()
        assert two_studios["event_b"].title == "Beta wedding"

    def test_create_always_uses_the_logged_in_studio(self, api, two_studios):
        self.login(api, two_studios["owner_a"].email)
        response = api.json(
            "post", "/api/v1/events", {"title": "New", "studio": str(two_studios["b"].pk)}
        )
        assert response.status_code == 201
        with tenancy.bypass_rls():
            assert Event.objects.get(pk=response.json()["id"]).studio_id == two_studios["a"].id

    def test_anonymous_requests_are_refused(self, api, two_studios):
        assert api.json("get", "/api/v1/events").status_code == 403
