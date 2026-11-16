import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.core import storage
from apps.core.tenancy import bypass_rls

from .models import Photo

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
            for key in (photo.preview_key, photo.thumb_key):
                if key:
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
                for key in (photo.preview_key, photo.thumb_key):
                    if key:
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
