"""Account emails. Each one is queued as a background job so requests never wait on SMTP."""

from django.conf import settings
from django.db import transaction

from .tasks import send_email


def _queue(to: str, subject: str, body: str) -> None:
    # Queue only after the surrounding transaction commits, so a rolled-back
    # signup never sends an email.
    transaction.on_commit(lambda: send_email.defer(to=to, subject=subject, body=body))


def verification_email(user, token: str) -> None:
    link = f"{settings.APP_URL}/verify-email?token={token}"
    _queue(
        user.email,
        "Confirm your email address",
        f"Hello {user.full_name},\n\n"
        f"Confirm your email address to finish setting up {user.studio.name}:\n\n{link}\n\n"
        "The link works for 3 days. If you did not sign up, ignore this email.",
    )


def password_reset_email(user, uid: str, token: str) -> None:
    link = f"{settings.APP_URL}/reset-password?uid={uid}&token={token}"
    _queue(
        user.email,
        "Reset your password",
        f"Hello {user.full_name},\n\nSet a new password here:\n\n{link}\n\n"
        "The link works for 3 days. If you did not ask for this, ignore this email.",
    )


def staff_invitation_email(user, invited_by, uid: str, token: str) -> None:
    link = f"{settings.APP_URL}/reset-password?uid={uid}&token={token}&invite=1"
    _queue(
        user.email,
        f"You have been added to {user.studio.name}",
        f"Hello {user.full_name},\n\n{invited_by.full_name} added you to {user.studio.name}.\n"
        f"Choose a password to sign in:\n\n{link}\n\nThe link works for 3 days.",
    )


def client_invitation_email(access, password: str) -> None:
    event, studio = access.event, access.studio
    link = f"{settings.APP_URL}/gallery/login?u={access.username}"
    limit = (
        f"You can choose up to {event.selection_limit} photos.\n"
        if event.selection_limit
        else "Choose as many photos as you like.\n"
    )
    expiry = f"The gallery is open until {event.expires_at:%d %B %Y}.\n" if event.expires_at else ""
    _queue(
        access.email,
        f"Your photos from {studio.name} are ready to choose",
        f"Hello {access.client_name},\n\n"
        f"{studio.name} has shared the photos from {event.title}. Open the gallery, tap the photos "
        "you want printed, and submit when you are done. Your choices save as you go.\n\n"
        f"Gallery: {link}\nUsername: {access.username}\nPassword: {password}\n\n{limit}{expiry}",
    )


def selection_submitted_email(to: str, event, count: int, client_name: str) -> None:
    link = f"{settings.APP_URL}/events/{event.pk}"
    _queue(
        to,
        f"{client_name} submitted their selection for {event.title}",
        f"{client_name} selected {count} photos from {event.title} and submitted the selection.\n\n"
        f"See it here: {link}",
    )


def reminders_due_email(owner, items) -> None:
    """Tell a studio owner which clients have not chosen their photos yet."""
    from django.utils import timezone

    now = timezone.now()
    lines = []
    for item in items:
        a = item.access
        days = (now - a.created_at).days
        why = "gallery closes tomorrow" if item.reason == "expiring" else f"shared {days} days ago"
        lines.append(f"- {a.client_name}, {a.event.title}: {why}")
    count = len(items)
    noun = "client has" if count == 1 else "clients have"
    _queue(
        owner.email,
        f"{count} {noun} not chosen their photos yet",
        f"Hello {owner.full_name},\n\n{count} {noun} not submitted a selection yet:\n\n"
        + "\n".join(lines)
        + f"\n\nSend each a reminder on WhatsApp in one tap: {settings.APP_URL}/reminders",
    )
