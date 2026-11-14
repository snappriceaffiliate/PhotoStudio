"""Signed tokens for email verification and password links."""

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

_VERIFY_SALT = "accounts.verify-email"


def make_verification_token(user) -> str:
    return signing.dumps({"uid": str(user.pk), "email": user.email}, salt=_VERIFY_SALT)


def read_verification_token(token: str) -> dict | None:
    try:
        return signing.loads(token, salt=_VERIFY_SALT, max_age=settings.EMAIL_VERIFICATION_MAX_AGE)
    except signing.BadSignature:
        return None


def make_password_link_parts(user) -> tuple[str, str]:
    """uid and token for a password reset or staff invitation link."""
    return urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)


def user_from_password_link(model, uid: str, token: str):
    try:
        user = model.objects.get(pk=force_str(urlsafe_base64_decode(uid)), is_active=True)
    except (ValueError, TypeError, OverflowError, model.DoesNotExist):
        return None
    return user if default_token_generator.check_token(user, token) else None
