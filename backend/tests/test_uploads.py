"""Albums, the upload manifest, the 100 KB check and the photo list, including tenant isolation."""

import pytest

from apps.core import storage, tenancy
from apps.events.models import Album, Event
from apps.photos.models import Photo, UploadSession

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db

WEBP_HEAD = b"RIFF\x10\x00\x00\x00WEBPVP8 "


@pytest.fixture
def studio_a(api, make_studio):
    studio, owner = make_studio("alpha")
    with tenancy.bypass_rls():
        event = Event.objects.create(studio=studio, title="Wedding")
    api.json("post", "/api/v1/auth/login", {"email": owner.email, "password": PASSWORD})
    return {"studio": studio, "owner": owner, "event": event}


@pytest.fixture
def fake_storage(monkeypatch):
    """Stand-in for R2: records object sizes the test 'uploads', and deletions."""
    objects: dict[str, int] = {}
    deleted: list[str] = []
    monkeypatch.setattr(storage, "object_size", lambda key: objects.get(key))
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key))
    monkeypatch.setattr(storage, "read_prefix", lambda key: objects.get(f"{key}#head", WEBP_HEAD))
    monkeypatch.setattr(
        storage, "copy_object", lambda src, dst: objects.__setitem__(dst, objects[src])
    )
    return {"objects": objects, "deleted": deleted}


def start_upload(api, event, paths, album=None):
    upload = api.json("post", f"/api/v1/events/{event.pk}/uploads").json()["id"]
    files = [{"relative_path": p, "album_id": album} for p in paths]
    registered = api.json("post", f"/api/v1/uploads/{upload}/files", {"files": files})
    return upload, registered


def upload_and_confirm(api, fake_storage, upload, photo_ids, size=60_000):
    urls = api.json("post", f"/api/v1/uploads/{upload}/urls", {"photo_ids": photo_ids}).json()[
        "urls"
    ]
    with tenancy.bypass_rls():
        for photo in Photo.objects.filter(pk__in=photo_ids):
            preview, thumb = photo.incoming_keys()
            fake_storage["objects"][preview] = size
            fake_storage["objects"][thumb] = 20_000
    entries = [{"id": i, "width": 1600, "height": 1067, "source": "raw"} for i in photo_ids]
    return urls, api.json("post", f"/api/v1/uploads/{upload}/confirm", {"photos": entries})


class TestAlbums:
    def test_create_list_and_reject_duplicate_names(self, api, studio_a):
        event = studio_a["event"]
        assert (
            api.json("post", f"/api/v1/events/{event.pk}/albums", {"name": "Reception"}).status_code
            == 201
        )
        assert (
            api.json("post", f"/api/v1/events/{event.pk}/albums", {"name": "reception"}).status_code
            == 400
        )
        names = [a["name"] for a in api.json("get", f"/api/v1/events/{event.pk}/albums").json()]
        assert names == ["Reception"]

    def test_cannot_add_an_album_to_another_studios_event(self, api, studio_a, make_studio):
        studio_b, _ = make_studio("beta")
        with tenancy.bypass_rls():
            other = Event.objects.create(studio=studio_b, title="Theirs")
        response = api.json("post", f"/api/v1/events/{other.pk}/albums", {"name": "X"})
        assert response.status_code == 404


class TestUploadFlow:
    def test_full_run_marks_photos_ready_and_moves_event_to_uploading(
        self, api, studio_a, fake_storage
    ):
        event = studio_a["event"]
        upload, registered = start_upload(
            api, event, ["Ceremony/DSC_0001.NEF", "Ceremony/DSC_0002.NEF"]
        )
        files = registered.json()["files"]
        assert [f["status"] for f in files] == ["pending", "pending"]

        urls, confirmed = upload_and_confirm(api, fake_storage, upload, [f["id"] for f in files])
        assert all("X-Amz-Signature=" in u["preview_url"] for u in urls)
        assert {r["status"] for r in confirmed.json()["results"]} == {"ready"}

        totals = api.json("post", f"/api/v1/uploads/{upload}/complete").json()["totals"]
        assert totals["ready"] == 2
        event_data = api.json("get", f"/api/v1/events/{event.pk}").json()
        assert (event_data["status"], event_data["photo_count"]) == ("uploading", 2)

    def test_storage_keys_are_namespaced_by_studio_and_event(self, api, studio_a, fake_storage):
        event = studio_a["event"]
        upload, registered = start_upload(api, event, ["a.jpg"])
        photo_id = registered.json()["files"][0]["id"]
        api.json("post", f"/api/v1/uploads/{upload}/urls", {"photo_ids": [photo_id]})
        with tenancy.bypass_rls():
            photo = Photo.objects.get(pk=photo_id)
        assert (
            photo.preview_key
            == f"studios/{studio_a['studio'].pk}/events/{event.pk}/photos/{photo_id}/preview.webp"
        )

    def test_over_100_kb_is_refused_and_deleted(self, api, studio_a, fake_storage):
        upload, registered = start_upload(api, studio_a["event"], ["big.jpg"])
        photo_id = registered.json()["files"][0]["id"]
        _, confirmed = upload_and_confirm(
            api, fake_storage, upload, [photo_id], size=100 * 1024 + 1
        )
        result = confirmed.json()["results"][0]
        assert (result["status"], result["failure_reason"]) == ("failed", "Image is over 100 KB.")
        assert len(fake_storage["deleted"]) == 2

    def test_missing_upload_is_marked_failed(self, api, studio_a, fake_storage):
        upload, registered = start_upload(api, studio_a["event"], ["lost.jpg"])
        photo_id = registered.json()["files"][0]["id"]
        api.json("post", f"/api/v1/uploads/{upload}/urls", {"photo_ids": [photo_id]})
        entry = {"id": photo_id, "width": 10, "height": 10, "source": "jpeg"}
        result = api.json("post", f"/api/v1/uploads/{upload}/confirm", {"photos": [entry]}).json()
        assert result["results"][0]["failure_reason"] == "Upload did not arrive."

    def test_choosing_the_same_folder_again_resumes(self, api, studio_a, fake_storage):
        event = studio_a["event"]
        upload, registered = start_upload(api, event, ["x/1.jpg", "x/2.jpg"])
        first = registered.json()["files"]
        upload_and_confirm(api, fake_storage, upload, [first[0]["id"]])  # only one finished

        _, again = start_upload(api, event, ["x/1.jpg", "x/2.jpg", "x/3.jpg"])
        statuses = {f["relative_path"]: f["status"] for f in again.json()["files"]}
        assert statuses == {"x/1.jpg": "ready", "x/2.jpg": "pending", "x/3.jpg": "pending"}
        with tenancy.bypass_rls():
            assert Photo.objects.filter(event=event).count() == 3  # no duplicates

    def test_same_filename_in_two_folders_is_two_photos(self, api, studio_a):
        _, registered = start_upload(
            api, studio_a["event"], ["Cam A/IMG_0001.jpg", "Cam B/IMG_0001.jpg"]
        )
        assert len({f["id"] for f in registered.json()["files"]}) == 2

    def test_refuses_paths_that_escape_the_folder(self, api, studio_a):
        _, registered = start_upload(api, studio_a["event"], ["../secret.jpg"])
        assert registered.status_code == 400

    def test_refuses_an_album_from_another_event(self, api, studio_a):
        with tenancy.bypass_rls():
            other_event = Event.objects.create(studio=studio_a["studio"], title="Other")
            album = Album.objects.create(
                studio=studio_a["studio"], event=other_event, name="Elsewhere"
            )
        _, registered = start_upload(api, studio_a["event"], ["a.jpg"], album=str(album.pk))
        assert registered.status_code == 400

    def test_enforces_the_per_event_photo_limit(self, api, studio_a, settings):
        settings.MAX_PHOTOS_PER_EVENT = 2
        _, registered = start_upload(api, studio_a["event"], ["1.jpg", "2.jpg", "3.jpg"])
        assert registered.status_code == 400


class TestIsolation:
    def test_another_studio_cannot_use_my_upload_or_see_my_photos(
        self, api, studio_a, make_studio, fake_storage
    ):
        upload, registered = start_upload(api, studio_a["event"], ["a.jpg"])
        photo_id = registered.json()["files"][0]["id"]
        upload_and_confirm(api, fake_storage, upload, [photo_id])

        _, owner_b = make_studio("beta")
        api.json("post", "/api/v1/auth/logout")
        api.json("post", "/api/v1/auth/login", {"email": owner_b.email, "password": PASSWORD})
        for path, body in [
            (f"/api/v1/uploads/{upload}/files", {"files": [{"relative_path": "z.jpg"}]}),
            (f"/api/v1/uploads/{upload}/urls", {"photo_ids": [photo_id]}),
            (f"/api/v1/uploads/{upload}/complete", None),
        ]:
            assert api.json("post", path, body).status_code == 404
        assert api.json("get", f"/api/v1/events/{studio_a['event'].pk}/photos").status_code == 404

    @pytest.mark.parametrize("model", [Album, UploadSession, Photo])
    def test_row_level_security_covers_new_tables(self, studio_a, make_studio, model):
        studio_b, _ = make_studio("beta")
        with tenancy.bypass_rls():
            event_b = Event.objects.create(studio=studio_b, title="B")
            if model is Album:
                Album.objects.create(studio=studio_b, event=event_b, name="B album")
            elif model is UploadSession:
                UploadSession.objects.create(studio=studio_b, event=event_b)
            else:
                Photo.objects.create(
                    studio=studio_b, event=event_b, relative_path="b.jpg", original_filename="b.jpg"
                )
        with tenancy.studio_context(studio_a["studio"].pk):
            assert model.objects.count() == 0


class TestPhotoList:
    def test_pages_ready_photos_with_signed_urls(self, api, studio_a, fake_storage):
        event = studio_a["event"]
        upload, registered = start_upload(api, event, [f"p/{i:03}.jpg" for i in range(5)])
        ids = [f["id"] for f in registered.json()["files"]]
        upload_and_confirm(api, fake_storage, upload, ids[:4])  # one stays pending
        page1 = api.json("get", f"/api/v1/events/{event.pk}/photos?page_size=3").json()
        assert (page1["count"], page1["next_page"], len(page1["results"])) == (4, 2, 3)
        assert page1["results"][0]["relative_path"] == "p/000.jpg"
        assert "X-Amz-Signature=" in page1["results"][0]["thumb_url"]
        page2 = api.json("get", f"/api/v1/events/{event.pk}/photos?page_size=3&page=2").json()
        assert (len(page2["results"]), page2["next_page"]) == (1, None)
