from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone

from apps.core.models import TenantModel

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


class ClientAccess(TenantModel):
    """A client's login to one event. Clients are not platform users and see only that event.

    The main client (the couple, the family) chooses and submits. Family helpers, invited by
    the main client from the gallery or added by the studio, have their own login: they can
    choose photos and remove their own picks, but only the main client can submit.
    """

    class Role(models.TextChoices):
        MAIN = "main", "Main client"
        HELPER = "helper", "Family helper"

    MAX_HELPERS = 10

    event = models.ForeignKey(
        "events.Event", on_delete=models.CASCADE, related_name="client_accesses"
    )
    client_name = models.CharField(max_length=150)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MAIN)
    invited_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="helpers"
    )
    email = models.EmailField(blank=True)
    phone = models.CharField(
        max_length=16,
        blank=True,
        help_text="WhatsApp number with country code, digits only: 919876543210.",
    )
    username = models.CharField(max_length=60, unique=True)
    password_hash = models.CharField(max_length=256)
    is_active = models.BooleanField(default=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    # Reminders for clients who have not submitted (see reminders.py). The studio sends them
    # from its own WhatsApp; these record what it sent and when the owner was last emailed.
    reminder_count = models.PositiveSmallIntegerField(default=0)
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    reminder_emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.client_name} ({self.username})"

    @property
    def is_main(self) -> bool:
        return self.role == self.Role.MAIN

    def main_client(self) -> "ClientAccess | None":
        """The main client this login belongs to (itself for a main client)."""
        if self.is_main:
            return self
        if self.invited_by_id:
            return self.invited_by
        return (
            ClientAccess.objects.for_studio(self.studio_id)
            .filter(event_id=self.event_id, role=self.Role.MAIN)
            .first()
        )

    def set_password(self, raw: str) -> None:
        self.password_hash = make_password(raw)

    def check_password(self, raw: str) -> bool:
        return check_password(raw, self.password_hash)

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > timezone.now())

    def record_failure(self) -> None:
        self.failed_attempts += 1
        if self.failed_attempts >= MAX_FAILED_LOGINS:
            self.locked_until = timezone.now() + timedelta(minutes=LOCKOUT_MINUTES)
            self.failed_attempts = 0
        self.save(update_fields=["failed_attempts", "locked_until", "updated_at"])


class Selection(TenantModel):
    """One photo the client picked. At most one per photo; locked once the event is submitted."""

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="selections")
    photo = models.ForeignKey("photos.Photo", on_delete=models.CASCADE, related_name="selections")
    client_access = models.ForeignKey(
        ClientAccess, null=True, on_delete=models.SET_NULL, related_name="selections"
    )
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["event", "photo"], name="selection_one_per_photo")
        ]


class Submission(TenantModel):
    """The client's final submit. The event's selection is locked from then on."""

    event = models.OneToOneField(
        "events.Event", on_delete=models.CASCADE, related_name="submission"
    )
    client_access = models.ForeignKey(
        ClientAccess, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    photo_count = models.PositiveIntegerField()
    submitted_at = models.DateTimeField(default=timezone.now)
