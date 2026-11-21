from django.conf import settings
from django.contrib.auth import (
    authenticate,
    login,
    logout,
    password_validation,
    update_session_auth_hash,
)
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.audit.models import record
from apps.billing import entitlements
from apps.billing.models import Subscription
from apps.core.tenancy import studio_context
from apps.core.validators import has_control_chars
from apps.notifications import emails
from apps.studios.models import Studio

from . import tokens
from .models import User
from .permissions import (
    LOGIN_THROTTLES,
    PASSWORD_THROTTLES,
    SIGNUP_THROTTLES,
    IsStudioOwner,
    require_verified_email,
)
from .serializers import (
    EmailSerializer,
    LoginSerializer,
    MeSerializer,
    PasswordSetSerializer,
    SignupSerializer,
    StaffInviteSerializer,
    StaffSerializer,
    TokenSerializer,
)


def _me(user) -> dict:
    if not user.is_authenticated:
        return {"user": None}
    data = MeSerializer(user).data
    if user.studio_id:
        # Login and sign-up responses are built before the middleware knew the studio.
        with studio_context(user.studio_id):
            data["billing"] = entitlements.summary(user.studio_id)
    else:
        data["billing"] = None
    # Lets the screens match the server: WhatsApp-only sharing, and whether the studio has to
    # confirm its email before sharing (see CLIENT_EMAIL_SHARING in settings).
    data["sharing"] = {
        "client_email": settings.CLIENT_EMAIL_SHARING,
        "confirm_email_first": settings.REQUIRE_VERIFIED_EMAIL_TO_SHARE,
    }
    return {"user": data}


def _unique_slug(name: str) -> str:
    base = slugify(name)[:60] or "studio"
    slug, n = base, 2
    while Studio.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


class PublicView(APIView):
    permission_classes = [AllowAny]


@method_decorator(ensure_csrf_cookie, name="get")
class CsrfView(PublicView):
    """Sets the CSRF cookie the React app sends back in the X-CSRFToken header."""

    def get(self, request):
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(PublicView):
    def get(self, request):
        return Response(_me(request.user))


@method_decorator(csrf_protect, name="post")
class SignupView(PublicView):
    throttle_classes = SIGNUP_THROTTLES

    def post(self, request):
        data = SignupSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        with transaction.atomic():
            studio = Studio.objects.create(
                name=v["studio_name"],
                slug=_unique_slug(v["studio_name"]),
                phone=v["phone"],
                pincode=v["pincode"],
            )
            user = User.objects.create_user(
                email=v["email"],
                password=v["password"],
                full_name=v["full_name"],
                studio=studio,
                role=User.Role.OWNER,
            )
            with studio_context(studio.id):
                Subscription.start_trial(studio)
            emails.verification_email(user, tokens.make_verification_token(user))
        login(request, user)
        return Response(_me(user), status=status.HTTP_201_CREATED)


@method_decorator(csrf_protect, name="post")
class LoginView(PublicView):
    throttle_classes = LOGIN_THROTTLES

    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = authenticate(
            request,
            email=data.validated_data["email"].strip().lower(),
            password=data.validated_data["password"],
        )
        if user is None:
            return Response(
                {"detail": "Email or password is incorrect."}, status=status.HTTP_400_BAD_REQUEST
            )
        login(request, user)
        return Response(_me(user))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VerifyEmailView(PublicView):
    def post(self, request):
        data = TokenSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payload = tokens.read_verification_token(data.validated_data["token"])
        user = User.objects.filter(pk=payload["uid"]).first() if payload else None
        if user is None or user.email != payload["email"]:
            return Response(
                {"detail": "This link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not user.email_verified:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        if request.user.is_authenticated:
            request.user.refresh_from_db()
        return Response(_me(request.user))


class ResendVerificationView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = PASSWORD_THROTTLES

    def post(self, request):
        if not request.user.email_verified and request.user.studio_id:
            emails.verification_email(request.user, tokens.make_verification_token(request.user))
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="post")
class PasswordResetView(PublicView):
    throttle_classes = PASSWORD_THROTTLES

    def post(self, request):
        data = EmailSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = User.objects.filter(
            email=data.validated_data["email"].strip().lower(), is_active=True
        ).first()
        if user:
            uid, token = tokens.make_password_link_parts(user)
            emails.password_reset_email(user, uid, token)
        # Same answer whether or not the account exists, so emails cannot be probed.
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(csrf_protect, name="post")
class PasswordSetView(PublicView):
    """Completes a password reset or a staff invitation."""

    throttle_classes = PASSWORD_THROTTLES

    def post(self, request):
        data = PasswordSetSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        user = tokens.user_from_password_link(User, v["uid"], v["token"])
        if user is None:
            return Response(
                {"detail": "This link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            password_validation.validate_password(v["password"], user)
        except DjangoValidationError as exc:
            return Response({"password": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(v["password"])
        if not user.email_verified:
            user.email_verified_at = timezone.now()  # the link proves they own the address
        user.save(update_fields=["password", "email_verified_at"])
        login(request, user)
        return Response(_me(user))


class StaffListView(APIView):
    permission_classes = [IsStudioOwner]

    def get(self, request):
        members = User.objects.filter(studio_id=request.user.studio_id).order_by(
            "-role", "full_name"
        )
        return Response(StaffSerializer(members, many=True).data)

    def post(self, request):
        data = StaffInviteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        require_verified_email(request.user)
        entitlements.check_staff_limit(request.user.studio_id)
        with transaction.atomic():
            member = User.objects.create_user(
                email=data.validated_data["email"],
                full_name=data.validated_data["full_name"],
                studio_id=request.user.studio_id,
                role=User.Role.STAFF,
            )
            uid, token = tokens.make_password_link_parts(member)
            emails.staff_invitation_email(member, request.user, uid, token)
            record(request, "staff.invited", detail=member.email, studio_id=request.user.studio_id)
        return Response(StaffSerializer(member).data, status=status.HTTP_201_CREATED)


class StaffDetailView(APIView):
    permission_classes = [IsStudioOwner]

    def delete(self, request, pk):
        member = User.objects.filter(pk=pk, studio_id=request.user.studio_id).first()
        if member is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if member.is_owner:
            return Response(
                {"detail": "The studio owner cannot be removed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Django refuses sessions of inactive users, so access ends on their next request.
        member.is_active = False
        member.save(update_fields=["is_active"])
        record(request, "staff.removed", detail=member.email, studio_id=request.user.studio_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AccountView(APIView):
    """PATCH {full_name}: the logged-in person's own name."""

    permission_classes = [IsAuthenticated]

    def patch(self, request):
        name = request.data.get("full_name")
        name = name.strip() if isinstance(name, str) else ""
        if not name:
            return Response({"full_name": ["Enter your name."]}, status=400)
        if len(name) > 150:
            return Response({"full_name": ["Use at most 150 characters."]}, status=400)
        if has_control_chars(name):
            return Response({"full_name": ["Use plain text on one line."]}, status=400)
        request.user.full_name = name
        request.user.save(update_fields=["full_name"])
        return Response(_me(request.user))


class PasswordChangeThrottle(UserRateThrottle):
    scope = "password_change"


class PasswordChangeView(APIView):
    """POST {current_password, new_password}. Other sessions are signed out; this one stays."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [PasswordChangeThrottle]

    def post(self, request):
        current = request.data.get("current_password") or ""
        new = request.data.get("new_password") or ""
        user = request.user
        if not isinstance(current, str) or not user.check_password(current):
            return Response(
                {"current_password": ["This is not your current password."]}, status=400
            )
        if not isinstance(new, str) or not new:
            return Response({"new_password": ["Enter a new password."]}, status=400)
        try:
            password_validation.validate_password(new, user)
        except DjangoValidationError as exc:
            return Response({"new_password": exc.messages}, status=400)
        user.set_password(new)
        user.save(update_fields=["password"])
        update_session_auth_hash(request, user)
        record(request, "account.password_changed")
        return Response({"detail": "Password changed."})
