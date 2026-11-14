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


class EmailAndIpThrottle(SimpleRateThrottle):
    """Limits attempts per email address and per IP address together.

    Set `scope` on a subclass. Each request counts against both keys, so neither
    guessing many passwords for one account nor many accounts from one IP gets far.
    """

    def get_cache_key(self, request, view):
        email = (
            str(request.data.get("email", "")).strip().lower() if hasattr(request, "data") else ""
        )
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{email}|{self.get_ident(request)}",
        }


class LoginThrottle(EmailAndIpThrottle):
    scope = "login"


class SignupThrottle(EmailAndIpThrottle):
    scope = "signup"


class PasswordResetThrottle(EmailAndIpThrottle):
    scope = "password_reset"
