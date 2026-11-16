"""Sorting the photo list, deleting photos, and deleting whole events."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEntry
from apps.clients.models import ClientAccess, Selection
from apps.core import storage, tenancy
from apps.events.models import Event
from apps.photos import tasks
from apps.photos.models import Photo

from .conftest import PASSWORD
from .test_clients import make_event, outbox, photo_ids, shared  # noqa: F401 - shared fixtures

pytestmark = pytest.mark.django_db


@pytest.fixture
def deleted(monkeypatch):
    keys: list[str] = []
    monkeypatch.setattr(storage, "delete_keys", lambda ks: keys.extend(ks))
    return keys


def listing(api, event, query=""):
    return api.json("get", f"/api/v1/events/{event.pk}/photos?{query}")


def paths(response):
    return [p["relative_path"] for p in response.json()["results"]]


class TestSortingAndChosen:
    def test_sorts_by_name_and_by_upload_time(self, api, shared):
        event = shared["event"]
        with tenancy.bypass_rls():
            for i, photo in enumerate(Photo.objects.filter(event=event).order_by("relative_path")):
                # the last file was uploaded first
                Photo.objects.filter(pk=photo.pk).update(
                    created_at=timezone.now() - timedelta(minutes=i)
                )
        names = [f"Wedding/{i:03}.jpg" for i in range(5)]
        assert paths(listing(api, event)) == names
        assert paths(listing(api, event, "sort=name")) == names
        assert paths(listing(api, event, "sort=-name")) == names[::-1]
        assert paths(listing(api, event, "sort=newest")) == names
        assert paths(listing(api, event, "sort=oldest")) == names[::-1]

    def test_refuses_an_unknown_sort(self, api, shared):
        response = listing(api, shared["event"], "sort=random")
        assert response.status_code == 400

    def test_marks_the_photos_the_client_chose(self, api, shared):
        guest, event = shared["guest"], shared["event"]
        first = photo_ids(guest)[0]
        guest.json("put", f"/api/v1/client/selections/{first}")
        chosen = {p["id"]: p["chosen"] for p in listing(api, event).json()["results"]}
        assert chosen[first] is True
        assert sum(chosen.values()) == 1


class TestDeletingPhotos:
    def test_deletes_rows_and_stored_images(
        self, api, shared, deleted, django_capture_on_commit_callbacks
    ):
        event = shared["event"]
        ids = [p["id"] for p in listing(api, event).json()["results"]][:2]
        with django_capture_on_commit_callbacks(execute=True):
            response = api.json(
                "post", f"/api/v1/events/{event.pk}/photos/delete", {"photo_ids": ids}
            )
        assert response.status_code == 200
        assert response.json() == {"deleted": 2, "removed_from_selection": 0}
        assert listing(api, event).json()["count"] == 3
        assert sorted(deleted) == sorted(
            [f"k/Wedding/{i}/{kind}.webp" for i in (0, 1) for kind in ("p", "t")]
        )
        with tenancy.bypass_rls():
            assert AuditEntry.objects.filter(action="photos.deleted").count() == 1

    def test_a_chosen_photo_leaves_the_selection_too(self, api, shared, deleted):
        guest, event = shared["guest"], shared["event"]
        first = photo_ids(guest)[0]
        guest.json("put", f"/api/v1/client/selections/{first}")
        response = api.json(
            "post", f"/api/v1/events/{event.pk}/photos/delete", {"photo_ids": [first]}
        )
        assert response.json() == {"deleted": 1, "removed_from_selection": 1}
        with tenancy.bypass_rls():
            assert not Selection.objects.filter(photo_id=first).exists()

    def test_chosen_photos_cannot_be_deleted_from_a_sent_selection(self, api, shared, deleted):
        guest, event = shared["guest"], shared["event"]
        ids = photo_ids(guest)
        guest.json("put", f"/api/v1/client/selections/{ids[0]}")
        guest.json("post", "/api/v1/client/submit")
        refused = api.json(
            "post", f"/api/v1/events/{event.pk}/photos/delete", {"photo_ids": [ids[0], ids[1]]}
        )
        assert refused.status_code == 409
        assert "reopen" in refused.json()["detail"]
        assert listing(api, event).json()["count"] == 5  # nothing was deleted
        # Photos the client did not choose can still go.
        allowed = api.json(
            "post", f"/api/v1/events/{event.pk}/photos/delete", {"photo_ids": [ids[1]]}
        )
        assert allowed.json()["deleted"] == 1

    def test_photos_of_another_studio_are_untouched(self, api, shared, make_studio, deleted):
        other_studio, _ = make_studio("beta")
        other = make_event(other_studio, title="Other")
        with tenancy.bypass_rls():
            other_ids = [
                str(p) for p in Photo.objects.filter(event=other).values_list("pk", flat=True)
            ]
        response = api.json(
            "post", f"/api/v1/events/{shared['event'].pk}/photos/delete", {"photo_ids": other_ids}
        )
        assert response.json()["deleted"] == 0
        with tenancy.bypass_rls():
            assert Photo.objects.filter(event=other).count() == 5
        assert (
            api.json(
                "post", f"/api/v1/events/{other.pk}/photos/delete", {"photo_ids": other_ids}
            ).status_code
            == 404
        )

    def test_needs_a_list_of_ids(self, api, shared):
        url = f"/api/v1/events/{shared['event'].pk}/photos/delete"
        assert api.json("post", url, {"photo_ids": []}).status_code == 400
        assert api.json("post", url, {"photo_ids": ["not-an-id"]}).status_code == 400


class TestDeletingEvents:
    def test_the_owner_deletes_everything_and_the_files_are_queued(
        self, api, shared, monkeypatch, django_capture_on_commit_callbacks
    ):
        event, guest = shared["event"], shared["guest"]
        guest.json("put", f"/api/v1/client/selections/{photo_ids(guest)[0]}")
        queued = []
        monkeypatch.setattr(tasks.delete_event_files, "defer", lambda **kw: queued.append(kw))
        with django_capture_on_commit_callbacks(execute=True):
            response = api.json("delete", f"/api/v1/events/{event.pk}")
        assert response.status_code == 204
        assert queued == [{"studio_id": str(event.studio_id), "event_id": str(event.pk)}]
        with tenancy.bypass_rls():
            assert not Event.objects.filter(pk=event.pk).exists()
            assert not Photo.objects.filter(event_id=event.pk).exists()
            assert not ClientAccess.objects.filter(event_id=event.pk).exists()
            assert not Selection.objects.filter(event_id=event.pk).exists()
            entry = AuditEntry.objects.get(action="event.deleted")
        assert "Wedding (5 photos)" in entry.detail
        assert guest.json("get", "/api/v1/client/me").status_code == 403  # the gallery is gone

    def test_staff_cannot_delete_an_event(self, api, shared):
        with tenancy.bypass_rls():
            User.objects.create_user(
                email="staff@alpha.test",
                password=PASSWORD,
                full_name="Staff",
                studio=shared["studio"],
                role=User.Role.STAFF,
                email_verified_at=timezone.now(),
            )
        api.json("post", "/api/v1/auth/logout")
        api.json("post", "/api/v1/auth/login", {"email": "staff@alpha.test", "password": PASSWORD})
        response = api.json("delete", f"/api/v1/events/{shared['event'].pk}")
        assert response.status_code == 403
        assert "owner" in response.json()["detail"]

    def test_another_studios_event_cannot_be_deleted(self, api, shared, make_studio):
        other_studio, _ = make_studio("beta")
        other = make_event(other_studio, title="Other")
        assert api.json("delete", f"/api/v1/events/{other.pk}").status_code == 404
        with tenancy.bypass_rls():
            assert Event.objects.filter(pk=other.pk).exists()


class TestCleaningUpFiles:
    def test_the_job_deletes_the_events_files_and_its_unfinished_uploads(self, monkeypatch):
        listed, removed = [], []
        files = {
            "studios/s1/events/e1/": ["studios/s1/events/e1/photos/p1/preview.webp"],
            "incoming/studios/s1/events/e1/": [
                "incoming/studios/s1/events/e1/photos/p2/n/thumb.webp"
            ],
        }
        monkeypatch.setattr(
            storage, "list_keys", lambda prefix: listed.append(prefix) or files[prefix]
        )
        monkeypatch.setattr(storage, "delete_keys", lambda keys: removed.extend(keys))
        assert tasks.delete_event_files(studio_id="s1", event_id="e1") == 2
        assert listed == ["studios/s1/events/e1/", "incoming/studios/s1/events/e1/"]
        assert len(removed) == 2

    def test_storage_deletes_in_batches_of_a_thousand(self, monkeypatch):
        calls = []

        class Client:
            def delete_objects(self, Bucket, Delete):
                calls.append(len(Delete["Objects"]))

        monkeypatch.setattr(storage, "internal_client", lambda: Client())
        storage.delete_keys([f"k{i}" for i in range(2500)])
        assert calls == [1000, 1000, 500]
        storage.delete_keys([])
        assert calls == [1000, 1000, 500]
