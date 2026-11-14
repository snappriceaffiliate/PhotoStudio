from django.conf import settings
from django.db import models

from apps.core.models import TenantModel


class AuditEntry(TenantModel):
    """Who did what to a studio's data: shares, logins turned off, submissions, exports."""

    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_label = models.CharField(max_length=200, help_text="Who acted, readable after deletion.")
    action = models.CharField(max_length=60)
    event = models.ForeignKey(
        "events.Event", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    detail = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["studio", "-created_at"], name="audit_studio_recent")]

    def __str__(self) -> str:
        return f"{self.actor_label}: {self.action}"


def record(request, action: str, event=None, detail: str = "", studio_id=None) -> None:
    """Add an audit entry for the current studio user or client."""
    user = getattr(request, "user", None)
    client = getattr(request, "client", None)
    if user is not None and user.is_authenticated:
        actor, label = user, f"{user.full_name} <{user.email}>"
    elif client is not None:
        actor, label = None, f"Client {client.client_name} ({client.username})"
    else:
        actor, label = None, "System"
    AuditEntry.objects.create(
        studio_id=studio_id or getattr(request, "studio_id", None) or event.studio_id,
        actor_user=actor,
        actor_label=label,
        action=action,
        event=event,
        detail=detail[:500],
    )
