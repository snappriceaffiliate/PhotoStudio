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
