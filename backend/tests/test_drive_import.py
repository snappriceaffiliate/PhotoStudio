"""Importing photos from a shared Google Drive folder."""

import io
import random

import pytest
from PIL import Image, ImageDraw, ImageFilter

from apps.core import storage, tenancy
from apps.events.models import Album, Event
from apps.photos import drive, tasks
from apps.photos.models import DriveImport, Photo

from .test_uploads import studio_a  # noqa: F401 - shared fixture

pytestmark = pytest.mark.django_db
FOLDER = "1AbCdEfGhIjKlMnOpQrStUv"


def noisy_jpeg(width=3000, height=2000) -> bytes:
    """A detailed, photo-like picture: soft colour blobs over fine grain."""
    rng = random.Random(1)
    image = Image.new("RGB", (width, height), (90, 60, 120))
    draw = ImageDraw.Draw(image)
    for _ in range(400):
        x, y, r = rng.randrange(width), rng.randrange(height), rng.randrange(10, width // 8)
        colour = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        draw.ellipse((x - r, y - r, x + r, y + r), fill=colour)
    image = image.filter(ImageFilter.GaussianBlur(6))
    grain = Image.effect_noise((width, height), 24).convert("RGB")
    image = Image.blend(image, grain, 0.12)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue()


@pytest.fixture
def key(settings):
    settings.GOOGLE_API_KEY = "test-key"


@pytest.fixture
def stored(monkeypatch):
    objects: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put_object", lambda k, data, ct: objects.__setitem__(k, data))
    monkeypatch.setattr(storage, "internal_client", lambda: None)
    return objects


def drive_files(*paths):
    return [
        drive.DriveFile(id=f"id-{p}", path=p, mime_type="image/jpeg", thumbnail_link="", size=1)
        for p in paths
    ]


class TestLinks:
    @pytest.mark.parametrize(
        "link",
        [
            f"https://drive.google.com/drive/folders/{FOLDER}",
            f"https://drive.google.com/drive/folders/{FOLDER}?usp=sharing",
            f"https://drive.google.com/drive/u/1/folders/{FOLDER}",
            f"https://drive.google.com/open?id={FOLDER}",
            FOLDER,
        ],
    )
    def test_finds_the_folder_id(self, link):
        assert drive.folder_id_from_link(link) == FOLDER

    @pytest.mark.parametrize(
        "link", ["", "https://example.com/folders/abcdefghijkl", "https://drive.google.com/", "x"]
    )
    def test_refuses_other_links(self, link):
        with pytest.raises(drive.DriveError):
            drive.folder_id_from_link(link)


class TestListing:
    def test_walks_subfolders_and_keeps_only_images(self, monkeypatch, settings):
        settings.GOOGLE_API_KEY = "k"
        pages = {
            FOLDER: [
                {"id": "f1", "name": "Ceremony", "mimeType": drive.FOLDER},
                {"id": "a", "name": "IMG_2.jpg", "mimeType": "image/jpeg", "size": "10"},
                {"id": "n", "name": "notes.txt", "mimeType": "text/plain"},
            ],
            "f1": [
                {"id": "b", "name": 'IMG_1"x.jpg', "mimeType": "image/jpeg"},
                {"id": "f1", "name": "Loop", "mimeType": drive.FOLDER},
            ],
        }

        def fake(url, params):
            if "q" not in params:
                return {"id": FOLDER, "name": "Wedding", "mimeType": drive.FOLDER}
            folder = params["q"].split("'")[1]
            return {"files": pages[folder]}

        monkeypatch.setattr(drive, "_get_json", fake)
        name, files = drive.list_folder(FOLDER)
        assert name == "Wedding"
        assert [f.path for f in files] == ["Ceremony/IMG_1_x.jpg", "IMG_2.jpg"]

    def test_a_file_link_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            drive, "_get_json", lambda url, params: {"id": FOLDER, "mimeType": "image/jpeg"}
        )
        with pytest.raises(drive.DriveError, match="not a folder"):
            drive.list_folder(FOLDER)


class TestImage:
    def test_a_detailed_photo_fits_under_the_limit_with_a_watermark(self, settings):
        image, width, height = drive.make_image(noisy_jpeg(), "Lens and Light")
        assert len(image) <= settings.MAX_IMAGE_BYTES == 40 * 1024
        assert image[8:12] == b"WEBP"
        assert max(width, height) <= 1200
        assert round(width / height, 1) == 1.5

    def test_a_simple_photo_keeps_full_size(self):
        out = io.BytesIO()
        Image.new("RGB", (2400, 1600), (200, 120, 40)).save(out, "JPEG")
        _, width, height = drive.make_image(out.getvalue())
        assert (width, height) == (1200, 800)


class TestJob:
    def start(self, studio_a, album=None):  # noqa: F811
        with tenancy.bypass_rls():
            return DriveImport.objects.create(
                studio=studio_a["studio"], event=studio_a["event"], folder_id=FOLDER, album=album
            )

    def test_imports_new_photos_and_skips_ones_already_there(
        self,
        studio_a,
        stored,
        monkeypatch,  # noqa: F811
    ):
        event = studio_a["event"]
        with tenancy.bypass_rls():
            Event.objects.filter(pk=event.pk).update(
                watermark_enabled=True, watermark_text="Lens and Light"
            )
            Photo.objects.create(
                studio=studio_a["studio"],
                event=event,
                relative_path="Day/IMG_1.jpg",
                original_filename="IMG_1.jpg",
                status=Photo.Status.READY,
            )
            album = Album.objects.create(studio=studio_a["studio"], event=event, name="Drive")
        monkeypatch.setattr(
            drive,
            "list_folder",
            lambda fid: ("Wedding", drive_files("Day/IMG_1.jpg", "Day/IMG_2.jpg", "IMG_3.jpg")),
        )
        photo = noisy_jpeg(1200, 800)
        monkeypatch.setattr(drive, "source_image", lambda file: photo)
        job = self.start(studio_a, album)

        assert tasks.import_drive_folder(import_id=str(job.pk)) == {
            "imported": 2,
            "skipped": 1,
            "failed": 0,
        }
        with tenancy.bypass_rls():
            job.refresh_from_db()
            new = list(Photo.objects.filter(event=event, source=Photo.Source.DRIVE))
            event.refresh_from_db()
        assert (job.status, job.folder_name, job.total) == ("done", "Wedding", 3)
        assert sorted(p.relative_path for p in new) == ["Day/IMG_2.jpg", "IMG_3.jpg"]
        for p in new:
            assert p.status == Photo.Status.READY and p.album_id == album.pk
            assert p.preview_key == p.thumb_key == p.final_key()
            assert len(stored[p.final_key()]) == p.preview_bytes <= 40 * 1024
        assert event.status == Event.Status.UPLOADING

    def test_a_photo_that_cannot_be_fetched_is_listed(self, studio_a, stored, monkeypatch):  # noqa: F811
        monkeypatch.setattr(drive, "list_folder", lambda fid: ("W", drive_files("a.jpg", "b.NEF")))

        def source(file):
            if file.path == "b.NEF":
                raise drive.DriveError("Google has no preview of this file.")
            return noisy_jpeg(800, 600)

        monkeypatch.setattr(drive, "source_image", source)
        job = self.start(studio_a)
        tasks.import_drive_folder(import_id=str(job.pk))
        with tenancy.bypass_rls():
            job.refresh_from_db()
            failed = Photo.objects.get(relative_path="b.NEF")
        assert (job.imported, job.failed) == (1, 1)
        assert job.failures == [{"path": "b.NEF", "reason": "Google has no preview of this file."}]
        assert failed.status == Photo.Status.FAILED

    def test_a_folder_that_cannot_be_opened_stops_with_the_reason(
        self,
        studio_a,
        monkeypatch,  # noqa: F811
    ):
        def refuse(fid):
            raise drive.DriveError("Could not open this folder.")

        monkeypatch.setattr(drive, "list_folder", refuse)
        job = self.start(studio_a)
        tasks.import_drive_folder(import_id=str(job.pk))
        with tenancy.bypass_rls():
            job.refresh_from_db()
        assert (job.status, job.error) == ("failed", "Could not open this folder.")

    def test_stops_at_the_plan_photo_limit(self, studio_a, stored, monkeypatch):  # noqa: F811
        from apps.billing import entitlements

        monkeypatch.setattr(entitlements, "photo_limit", lambda studio_id: 1)
        monkeypatch.setattr(drive, "list_folder", lambda fid: ("W", drive_files("a.jpg", "b.jpg")))
        monkeypatch.setattr(drive, "source_image", lambda f: noisy_jpeg(400, 300))
        job = self.start(studio_a)
        tasks.import_drive_folder(import_id=str(job.pk))
        with tenancy.bypass_rls():
            job.refresh_from_db()
        assert (job.imported, job.failed) == (1, 1)
        assert "photo limit" in job.failures[0]["reason"]


class TestApi:
    def url(self, studio_a):  # noqa: F811
        return f"/api/v1/events/{studio_a['event'].pk}/drive-imports"

    def test_hidden_until_a_google_key_is_set(self, api, studio_a, settings):  # noqa: F811
        settings.GOOGLE_API_KEY = ""
        assert api.json("get", self.url(studio_a)).json() == {"enabled": False, "imports": []}
        response = api.json("post", self.url(studio_a), {"link": FOLDER})
        assert response.status_code == 400

    def test_starts_an_import_and_queues_the_job(
        self,
        api,
        studio_a,
        key,
        monkeypatch,
        django_capture_on_commit_callbacks,  # noqa: F811
    ):
        queued = []
        monkeypatch.setattr(tasks.import_drive_folder, "defer", lambda **kw: queued.append(kw))
        with django_capture_on_commit_callbacks(execute=True):
            response = api.json(
                "post",
                self.url(studio_a),
                {"link": f"https://drive.google.com/drive/folders/{FOLDER}"},
            )
        assert response.status_code == 201
        assert response.json()["status"] == "queued"
        assert queued == [{"import_id": response.json()["id"]}]
        listed = api.json("get", self.url(studio_a)).json()
        assert listed["enabled"] is True and listed["imports"][0]["id"] == response.json()["id"]
        # A second import waits for the first.
        again = api.json("post", self.url(studio_a), {"link": FOLDER})
        assert again.status_code == 409

    def test_a_bad_link_is_explained(self, api, studio_a, key):  # noqa: F811
        response = api.json("post", self.url(studio_a), {"link": "https://example.com/photos"})
        assert response.status_code == 400
        assert "Google Drive folder link" in response.json()["link"][0]

    def test_another_studios_event_is_not_found(self, api, studio_a, make_studio, key):  # noqa: F811
        other_studio, _ = make_studio("beta")
        with tenancy.bypass_rls():
            other = Event.objects.create(studio=other_studio, title="Theirs")
        response = api.json("post", f"/api/v1/events/{other.pk}/drive-imports", {"link": FOLDER})
        assert response.status_code == 404
