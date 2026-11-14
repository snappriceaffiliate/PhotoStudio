from django.conf import settings
from django.db import models

from apps.core.models import TenantModel


class UploadSession(TenantModel):
    """One run of the uploader for one event: the manifest that makes uploads resumable.

    Each file in the run is a Photo row that starts as PENDING and becomes READY once both
    compressed images are stored and checked. Choosing the same folder again resumes: photos
    that are already READY are skipped.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        COMPLETED = "completed", "Completed"

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="uploads")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True)


class Photo(TenantModel):
    """One photo of an event: a preview and a thumbnail in storage, both at most 100 KB.

    The original never leaves the studio's computer. `relative_path` (folder plus filename,
    as chosen in the uploader) is what maps a client's selection back to that original;
    the filename alone can repeat across folders or cameras.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    class Source(models.TextChoices):
        RAW = "raw", "RAW embedded preview"
        JPEG = "jpeg", "JPEG"

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="photos")
    album = models.ForeignKey(
        "events.Album", null=True, blank=True, on_delete=models.SET_NULL, related_name="photos"
    )
    upload = models.ForeignKey(
        UploadSession, null=True, blank=True, on_delete=models.SET_NULL, related_name="photos"
    )
    original_filename = models.CharField(max_length=255)
    relative_path = models.CharField(max_length=1024)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    failure_reason = models.CharField(max_length=200, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, blank=True)
    preview_key = models.CharField(max_length=300, blank=True)
    thumb_key = models.CharField(max_length=300, blank=True)
    preview_bytes = models.PositiveIntegerField(null=True, blank=True)
    thumb_bytes = models.PositiveIntegerField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "relative_path"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "relative_path"], name="photo_unique_path_per_event"
            )
        ]
        indexes = [
            models.Index(fields=["event", "status", "sort_order"], name="photo_event_gallery"),
            models.Index(fields=["event", "album", "sort_order"], name="photo_album_gallery"),
        ]

    def __str__(self) -> str:
        return self.relative_path

    def storage_prefix(self) -> str:
        return f"studios/{self.studio_id}/events/{self.event_id}/photos/{self.pk}"
