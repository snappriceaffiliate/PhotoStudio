from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.throttling import SimpleRateThrottle


class IsStudioMember(BasePermission):
    """Logged in as an owner or staff member of a studio."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.studio_id)


class IsStudioOwner(IsStudioMember):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.is_owner


class FieldThrottle(SimpleRateThrottle):
    """Counts attempts per value of one request field (an email or a username), across all
    IP addresses, so rotating addresses does not give more guesses at one account."""

    field = "email"

    def get_cache_key(self, request, view):
        value = (
            str(request.data.get(self.field, "")).strip().lower()
            if hasattr(request, "data")
            else ""
        )
        if not value:
            return None
        return self.cache_format % {"scope": self.scope, "ident": value}


class IpThrottle(SimpleRateThrottle):
    """Counts attempts per client IP address, across all accounts. The address comes from
    the hosting proxy's X-Forwarded-For entry (REST_FRAMEWORK NUM_PROXIES), not from the
    client, so it cannot be forged."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginEmailThrottle(FieldThrottle):
    scope = "login_account"


class LoginIpThrottle(IpThrottle):
    scope = "login_ip"


class SignupIpThrottle(IpThrottle):
    scope = "signup_ip"


class PasswordResetEmailThrottle(FieldThrottle):
    scope = "password_reset_account"


class PasswordResetIpThrottle(IpThrottle):
    scope = "password_reset_ip"


LOGIN_THROTTLES = [LoginEmailThrottle, LoginIpThrottle]
SIGNUP_THROTTLES = [SignupIpThrottle]
PASSWORD_THROTTLES = [PasswordResetEmailThrottle, PasswordResetIpThrottle]


def require_verified_email(user) -> None:
    """Sending email to other people (clients, staff) needs a confirmed address, so a
    throwaway sign-up cannot be used to send invitations to strangers."""
    if not user.email_verified:
        raise PermissionDenied(
            "Confirm your email address first, using the link we sent you. "
            "You can send a new link from the banner at the top of the page."
        )
