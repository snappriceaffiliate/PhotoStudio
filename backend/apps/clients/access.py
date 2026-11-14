"""Client sessions and generated credentials."""

import secrets

from django.utils import timezone
from django.utils.text import slugify
from rest_framework.permissions import BasePermission

from apps.core.tenancy import bypass_rls
from apps.events.models import Event

from .models import ClientAccess

SESSION_KEYS = ("client_access_id", "client_event_id", "client_studio_id")
# No look-alike characters (0/O, 1/l/I), so clients can type passwords from an email or a phone.
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
GALLERY_STATUSES = {Event.Status.SHARED, Event.Status.SUBMITTED}


def generate_password() -> str:
    groups = ["".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "-".join(groups)


def generate_username(client_name: str) -> str:
    base = slugify(client_name).split("-")[0][:20] or "client"
    with bypass_rls():  # usernames are unique across all studios
        while True:
            candidate = f"{base}-{secrets.randbelow(9000) + 1000}"
            if not ClientAccess.objects.filter(username=candidate).exists():
                return candidate


def start_session(request, access: ClientAccess) -> None:
    request.session.cycle_key()
    request.session["client_access_id"] = str(access.pk)
    request.session["client_event_id"] = str(access.event_id)
    request.session["client_studio_id"] = str(access.studio_id)


def end_session(request) -> None:
    for key in SESSION_KEYS:
        request.session.pop(key, None)


def unavailable_reason(access: ClientAccess) -> str | None:
    """Why this client cannot use the gallery right now, or None if they can."""
    event = access.event
    if not access.is_active:
        return "This gallery link has been turned off by the studio."
    if event.expires_at and event.expires_at < timezone.localdate():
        return "This gallery has expired. Contact the studio if you still need it."
    if event.status not in GALLERY_STATUSES:
        return "This gallery is not available. Contact the studio."
    return None


class IsClient(BasePermission):
    """A logged-in client whose gallery is still open. Sets request.client."""

    message = "Please log in to the gallery."

    def has_permission(self, request, view):
        access_id = request.session.get("client_access_id")
        if not access_id:
            return False
        access = (
            ClientAccess.objects.for_studio(request.session.get("client_studio_id"))
            .select_related("event", "studio")
            .filter(pk=access_id)
            .first()
        )
        if access is None or unavailable_reason(access):
            end_session(request)
            return False
        request.client = access
        return True
