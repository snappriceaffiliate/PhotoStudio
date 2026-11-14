"""Selection review, export formats, archiving, image retention and the audit log."""

import datetime
import shutil
import subprocess
from pathlib import Path

import pytest
from django.utils import timezone

from apps.audit.models import AuditEntry
from apps.core import storage, tenancy
from apps.events.models import Event
from apps.photos import tasks
from apps.photos.models import Photo

from .conftest import PASSWORD
from .test_clients import outbox, photo_ids, shared  # noqa: F401 - shared fixtures

pytestmark = pytest.mark.django_db


@pytest.fixture
def selected(shared):
    """The shared event with two photos selected, one with a note, and a submission."""
    guest = shared["guest"]
    ids = photo_ids(guest)
    guest.json("put", f"/api/v1/client/selections/{ids[2]}", {"note": "Cover, please"})
    guest.json("put", f"/api/v1/client/selections/{ids[0]}")
    guest.json("post", "/api/v1/client/submit")
    return shared


def export(api, event, fmt):
    return api.get(f"/api/v1/events/{event.pk}/export?type={fmt}")


class TestSelectionReview:
    def test_lists_selected_photos_in_upload_order_with_notes(self, api, selected):
        data = api.json("get", f"/api/v1/events/{selected['event'].pk}/selection").json()
        assert data["count"] == 2
        assert [r["relative_path"] for r in data["results"]] == [
            "Wedding/000.jpg",
            "Wedding/002.jpg",
        ]
        assert data["results"][1]["note"] == "Cover, please"
        assert "X-Amz-Signature=" in data["results"][0]["thumb_url"]


class TestExports:
    def test_csv_has_paths_notes_and_opens_in_excel(self, api, selected):
        response = export(api, selected["event"], "csv")
        assert response["Content-Disposition"] == 'attachment; filename="wedding-selection.csv"'
        text = response.content.decode("utf-8-sig")
        lines = text.strip().splitlines()
        assert lines[0].startswith("number,folder,filename,path,album,note")
        assert lines[2].startswith('2,Wedding,002.jpg,Wedding/002.jpg,,"Cover, please"')

    def test_text_list_and_lightroom_filter(self, api, selected):
        assert (
            export(api, selected["event"], "txt").content.decode()
            == "Wedding/000.jpg\nWedding/002.jpg\n"
        )
        assert export(api, selected["event"], "lightroom").content.decode() == "000, 002\n"

    def test_windows_script_uses_crlf_and_escapes_percent_signs(self, api, selected):
        with tenancy.bypass_rls():
            Photo.objects.filter(relative_path="Wedding/000.jpg").update(
                relative_path="Day 1/100% joy.jpg"
            )
        script = export(api, selected["event"], "script-windows").content.decode()
        assert "\r\n" in script
        assert "::P|Day 1|100% joy" in script  # a data line, never a command

    def test_unknown_format_and_empty_selection_are_refused(self, api, shared):
        assert export(api, shared["event"], "pdf").status_code == 400
        assert export(api, shared["event"], "csv").status_code == 400  # nothing selected yet

    def test_another_studio_cannot_export(self, api, selected, make_studio):
        _, owner_b = make_studio("beta")
        api.json("post", "/api/v1/auth/logout")
        api.json("post", "/api/v1/auth/login", {"email": owner_b.email, "password": PASSWORD})
        assert export(api, selected["event"], "csv").status_code == 404
        assert (
            api.json("get", f"/api/v1/events/{selected['event'].pk}/selection").status_code == 404
        )


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_mac_script_copies_selected_files_with_their_raw_and_sidecar_files(api, selected, tmp_path):
    with tenancy.bypass_rls():
        Photo.objects.filter(relative_path="Wedding/002.jpg").update(
            relative_path="Wedding/Cam B/it's 002.jpg"
        )
    folder: Path = tmp_path / "event"
    for name in [
        "Wedding/000.jpg",
        "Wedding/000.NEF",
        "Wedding/000.xmp",
        "Wedding/001.jpg",
        "Wedding/Cam B/it's 002.jpg",
    ]:
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(name)
    script = folder / "copy-selected.sh"
    script.write_bytes(export(api, selected["event"], "script-mac").content)

    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, check=True)

    copied = sorted(
        str(p.relative_to(folder / "Selected"))
        for p in (folder / "Selected").rglob("*")
        if p.is_file()
    )
    assert copied == [
        "Wedding/000.NEF",
        "Wedding/000.jpg",
        "Wedding/000.xmp",
        "Wedding/Cam B/it's 002.jpg",
    ]
    assert "Copied 2 of 2" in result.stdout


class TestArchive:
    def test_archive_closes_the_gallery_and_unarchive_restores_it(self, api, selected):
        event, guest = selected["event"], selected["guest"]
        assert api.json("post", f"/api/v1/events/{event.pk}/archive").json()["status"] == "archived"
        assert guest.json("get", "/api/v1/client/me").status_code == 403
        assert api.json("post", f"/api/v1/events/{event.pk}/uploads").status_code == 400
        assert (
            api.json("post", f"/api/v1/events/{event.pk}/unarchive").json()["status"] == "submitted"
        )

    def test_retention_job_removes_images_but_keeps_the_selection(self, api, selected, monkeypatch):
        deleted: list[str] = []
        monkeypatch.setattr(storage, "delete_object", deleted.append)
        event = selected["event"]
        api.json("post", f"/api/v1/events/{event.pk}/archive")
        with tenancy.bypass_rls():
            Event.objects.filter(pk=event.pk).update(
                archived_at=timezone.now() - datetime.timedelta(days=91)
            )

        assert tasks.remove_archived_images(timestamp=0) == 5
        assert len(deleted) == 10  # preview and thumbnail of each of the 5 photos
        assert tasks.remove_archived_images(timestamp=0) == 0  # runs once per event

        # The selection list and exports still work; the event cannot be reopened.
        assert export(api, event, "txt").content.decode() == "Wedding/000.jpg\nWedding/002.jpg\n"
        assert (
            api.json("get", f"/api/v1/events/{event.pk}/selection").json()["results"][0][
                "thumb_url"
            ]
            is None
        )
        assert api.json("post", f"/api/v1/events/{event.pk}/unarchive").status_code == 400

    def test_recently_archived_events_keep_their_images(self, api, selected):
        api.json("post", f"/api/v1/events/{selected['event'].pk}/archive")
        assert tasks.remove_archived_images(timestamp=0) == 0


class TestAuditLog:
    def test_records_who_shared_submitted_and_exported(self, api, selected):
        export(api, selected["event"], "csv")
        with tenancy.bypass_rls():
            entries = list(
                AuditEntry.objects.order_by("created_at").values_list("action", "actor_label")
            )
        actions = [a for a, _ in entries]
        assert actions == ["client.shared", "selection.submitted", "selection.exported"]
        assert entries[0][1].startswith("Owner alpha")
        assert entries[1][1].startswith("Client Priya Rao")
