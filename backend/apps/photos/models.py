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
    """One photo of an event: one small WebP image in storage (at most MAX_IMAGE_BYTES), used
    both as the thumbnail and as the preview. Older photos may still have two images, so
    `preview_key` and `thumb_key` stay; for new photos they hold the same key.

    The original never leaves the studio's computer. `relative_path` (folder plus filename,
    as chosen in the uploader) is what maps a client's selection back to that original;
    the filename alone can repeat across folders or cameras.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        REMOVED = "removed", "Images removed after archiving"

    class Source(models.TextChoices):
        RAW = "raw", "RAW embedded preview"
        JPEG = "jpeg", "JPEG"
        DRIVE = "drive", "Google Drive"

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
    upload_nonce = models.CharField(
        max_length=32, blank=True, help_text="Random part of the one-time incoming upload keys."
    )

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

    def final_key(self) -> str:
        return f"{self.storage_prefix()}/image.webp"

    def incoming_key(self) -> str:
        """Where the browser uploads. The checked image is copied to the final key, which no
        signed upload URL can write to, so a link reused after confirming changes nothing.
        Leftovers under incoming/ are removed by a storage lifecycle rule."""
        return f"incoming/{self.storage_prefix()}/{self.upload_nonce}/image.webp"

    def stored_keys(self) -> list[str]:
        """Every stored image of this photo, each once (old photos have two, new ones one)."""
        return list(dict.fromkeys(k for k in (self.preview_key, self.thumb_key) if k))


class DriveImport(TenantModel):
    """One import of a shared Google Drive folder into an event, run by a background job.

    Importing the same folder again only adds photos that are not in the event yet.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Waiting to start"
        RUNNING = "running", "Importing"
        DONE = "done", "Finished"
        FAILED = "failed", "Stopped"

    event = models.ForeignKey(
        "events.Event", on_delete=models.CASCADE, related_name="drive_imports"
    )
    album = models.ForeignKey(
        "events.Album", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    folder_id = models.CharField(max_length=200)
    folder_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    total = models.PositiveIntegerField(default=0)
    imported = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0, help_text="Already in the event.")
    failed = models.PositiveIntegerField(default=0)
    failures = models.JSONField(default=list, blank=True)
    error = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
