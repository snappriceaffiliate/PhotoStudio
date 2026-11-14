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
