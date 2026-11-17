import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from django.conf import settings
from django.db.models import Max
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.core import storage
from apps.core.tenancy import bypass_rls

from . import drive
from .models import DriveImport, Photo

logger = logging.getLogger(__name__)


@app.periodic(cron="30 3 * * *")  # every night at 03:30
@app.task(name="photos.cleanup_stale_uploads", queueing_lock="photos.cleanup_stale_uploads")
def cleanup_stale_uploads(timestamp: int) -> int:
    """Delete photos whose upload was abandoned (still PENDING or FAILED after 48 hours)."""
    cutoff = timezone.now() - timedelta(hours=settings.STALE_UPLOAD_HOURS)
    with bypass_rls():
        stale = Photo.objects.filter(
            status__in=[Photo.Status.PENDING, Photo.Status.FAILED], updated_at__lt=cutoff
        )
        removed = 0
        for photo in stale.iterator():
            for key in photo.stored_keys():
                storage.delete_object(key)
            photo.delete()
            removed += 1
    logger.info("Removed %s abandoned photos", removed)
    return removed


@app.periodic(cron="45 3 * * *")  # every night at 03:45
@app.task(name="photos.remove_archived_images", queueing_lock="photos.remove_archived_images")
def remove_archived_images(timestamp: int) -> int:
    """Delete stored images of events archived more than ARCHIVE_RETENTION_DAYS ago.

    Photo rows, selections and notes stay, so the selection list and exports keep working.
    """
    from apps.events.models import Event

    cutoff = timezone.now() - timedelta(days=settings.ARCHIVE_RETENTION_DAYS)
    removed = 0
    with bypass_rls():
        events = Event.objects.filter(
            status=Event.Status.ARCHIVED, archived_at__lt=cutoff, photos_deleted_at=None
        )
        for event in events:
            for photo in (
                Photo.objects.filter(event=event).exclude(status=Photo.Status.REMOVED).iterator()
            ):
                for key in photo.stored_keys():
                    storage.delete_object(key)
                photo.status, photo.preview_key, photo.thumb_key = Photo.Status.REMOVED, "", ""
                photo.save(update_fields=["status", "preview_key", "thumb_key", "updated_at"])
                removed += 1
            event.photos_deleted_at = timezone.now()
            event.save(update_fields=["photos_deleted_at", "updated_at"])
    logger.info("Removed images of %s photos from archived events", removed)
    return removed


@app.task(name="photos.delete_event_files", retry=5)
def delete_event_files(studio_id: str, event_id: str) -> int:
    """Deletes every stored image of a deleted event, including unfinished uploads.

    The event's rows are already gone when this runs; the files are removed here, in the
    background, because an event can have thousands of them.
    """
    prefix = f"studios/{studio_id}/events/{event_id}/"
    keys = storage.list_keys(prefix) + storage.list_keys(f"incoming/{prefix}")
    storage.delete_keys(keys)
    logger.info("Deleted %s stored files of event %s", len(keys), event_id)
    return len(keys)


DRIVE_WORKERS = 6
MAX_LISTED_FAILURES = 100


def _import_one(file, watermark: str, key: str) -> tuple[int, int, int]:
    """Fetches one photo from Drive, makes its image and stores it. Runs in a worker thread
    and touches no database rows."""
    image, width, height = drive.make_image(drive.source_image(file), watermark)
    storage.put_object(key, image, "image/webp")
    return len(image), width, height


@app.task(name="photos.import_drive_folder")
def import_drive_folder(import_id: str) -> dict:
    """Imports every photo of a shared Google Drive folder into the event.

    Photos already in the event (same folder path) are skipped, so running the same folder
    again only adds what is new. Progress is saved as it goes for the event page to show.
    """
    from apps.billing import entitlements
    from apps.events.models import Event

    with bypass_rls():
        job = DriveImport.objects.select_related("event").get(pk=import_id)
        event = job.event
        job.status, job.error = DriveImport.Status.RUNNING, ""
        job.save(update_fields=["status", "error", "updated_at"])
        try:
            folder_name, files = drive.list_folder(job.folder_id)
        except drive.DriveError as error:
            return _stop(job, str(error))
        except Exception:
            logger.exception("Listing Drive folder %s failed", job.folder_id)
            return _stop(job, "Could not read the folder from Google Drive. Try again later.")
        job.folder_name, job.total = folder_name[:255], len(files)
        job.save(update_fields=["folder_name", "total", "updated_at"])
        if not files:
            return _stop(job, "No photos were found in this folder.")

        photos = Photo.objects.filter(event=event)
        existing = {
            p.relative_path: p for p in photos.filter(relative_path__in=[f.path for f in files])
        }
        todo = [
            f for f in files if getattr(existing.get(f.path), "status", None) != Photo.Status.READY
        ]
        job.skipped = len(files) - len(todo)
        room = (
            entitlements.photo_limit(event.studio_id)
            - photos.exclude(relative_path__in=[f.path for f in todo]).count()
        )
        over_limit = todo[max(0, room) :]
        todo = todo[: max(0, room)]
        for file in over_limit:
            _failed(job, file.path, "The event has reached its photo limit.")

        next_order = (photos.aggregate(m=Max("sort_order"))["m"] or 0) + 1
        rows = {}
        for i, file in enumerate(todo):
            photo = existing.get(file.path) or Photo(
                studio_id=event.studio_id,
                event=event,
                relative_path=file.path,
                original_filename=file.path.rsplit("/", 1)[-1],
                sort_order=next_order + i,
            )
            photo.album_id, photo.status, photo.failure_reason = (
                job.album_id,
                Photo.Status.PENDING,
                "",
            )
            photo.save()
            rows[file.id] = photo
        if todo and event.status == Event.Status.DRAFT:
            event.status = Event.Status.UPLOADING
            event.save(update_fields=["status", "updated_at"])
        job.save()

        watermark = event.watermark_text.strip() if event.watermark_enabled else ""
        storage.internal_client()  # create the shared client once, before the threads use it
        with ThreadPoolExecutor(max_workers=DRIVE_WORKERS) as pool:
            futures = {
                pool.submit(_import_one, file, watermark, rows[file.id].final_key()): file
                for file in todo
            }
            for future in as_completed(futures):
                file, photo = futures[future], rows[futures[future].id]
                try:
                    size, width, height = future.result()
                except Exception as error:
                    reason = (
                        str(error)
                        if isinstance(error, drive.DriveError)
                        else "Could not fetch this photo from Google Drive."
                    )
                    if not isinstance(error, drive.DriveError):
                        logger.warning("Drive import of %s failed: %s", file.id, error)
                    photo.status, photo.failure_reason = Photo.Status.FAILED, reason[:200]
                    _failed(job, file.path, reason)
                else:
                    photo.preview_key = photo.thumb_key = photo.final_key()
                    photo.status, photo.failure_reason, photo.source = (
                        Photo.Status.READY,
                        "",
                        Photo.Source.DRIVE,
                    )
                    photo.preview_bytes, photo.thumb_bytes = size, None
                    photo.width, photo.height = width, height
                    job.imported += 1
                photo.save()
                job.save(update_fields=["imported", "failed", "failures", "updated_at"])

        job.status, job.finished_at = DriveImport.Status.DONE, timezone.now()
        job.save()
        record_summary = {"imported": job.imported, "skipped": job.skipped, "failed": job.failed}
        logger.info("Drive import %s finished: %s", job.pk, record_summary)
        return record_summary


def _failed(job: "DriveImport", path: str, reason: str) -> None:
    job.failed += 1
    if len(job.failures) < MAX_LISTED_FAILURES:
        job.failures = [*job.failures, {"path": path, "reason": reason[:200]}]


def _stop(job: "DriveImport", message: str) -> dict:
    job.status, job.error, job.finished_at = (
        DriveImport.Status.FAILED,
        message[:500],
        timezone.now(),
    )
    job.save()
    return {"error": message}
