from django.conf import settings
from django.db import models

from apps.core.models import TenantModel


class Event(TenantModel):
    """One shoot shared with one client. Albums, photos and selections hang off it."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        UPLOADING = "uploading", "Ready to share"
        SHARED = "shared", "Shared"
        SUBMITTED = "submitted", "Submitted"
        ARCHIVED = "archived", "Archived"

    title = models.CharField(max_length=200)
    event_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    selection_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="How many photos the client may select; empty means no limit.",
    )
    expires_at = models.DateField(
        null=True, blank=True, help_text="The client link stops working after this date."
    )
    watermark_enabled = models.BooleanField(default=False)
    watermark_text = models.CharField(max_length=80, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    photos_deleted_at = models.DateTimeField(
        null=True, blank=True, help_text="When the stored images were removed after archiving."
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["studio", "status"], name="event_studio_status")]

    def __str__(self) -> str:
        return self.title


class Album(TenantModel):
    """Optional grouping inside an event, for example Engagement, Wedding, Reception."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="albums")
    name = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["event", "name"], name="album_unique_name_per_event")
        ]

    def __str__(self) -> str:
        return self.name
