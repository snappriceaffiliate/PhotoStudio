import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import (
    FieldThrottle,
    IpThrottle,
    IsStudioMember,
    require_verified_email,
)
from apps.audit.models import record
from apps.billing import entitlements
from apps.core import storage
from apps.core.tenancy import bypass_rls
from apps.core.validators import single_line, whatsapp_number
from apps.events.models import Album, Event
from apps.notifications import emails
from apps.photos.models import Photo
from apps.studios.views import client_branding

from . import access as client_access
from .models import ClientAccess, Selection, Submission

PAGE_SIZE_MAX = 200

# ---------------------------------------------------------------- studio side


class ShareRequest(serializers.Serializer):
    client_name = serializers.CharField(max_length=150, validators=[single_line])
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="", max_length=30)

    def validate_phone(self, value):
        return whatsapp_number(value) if value.strip() else ""

    def validate(self, attrs):
        if not settings.CLIENT_EMAIL_SHARING:
            # WhatsApp only: no client emails are stored or sent.
            if not attrs["phone"]:
                raise serializers.ValidationError(
                    {"phone": ["Enter the client's WhatsApp number."]}
                )
            attrs["email"] = ""
            return attrs
        if not attrs["email"] and not attrs["phone"]:
            raise serializers.ValidationError(
                {"email": ["Enter the client's email, WhatsApp number, or both."]}
            )
        return attrs


def _access_data(a: ClientAccess) -> dict:
    return {
        "id": str(a.pk),
        "client_name": a.client_name,
        "email": a.email,
        "phone": a.phone,
        "username": a.username,
        "is_active": a.is_active,
        "last_login_at": a.last_login_at,
        "created_at": a.created_at,
    }


def _studio_event(request, event_id) -> Event:
    return get_object_or_404(Event.objects.for_studio(request.studio_id), pk=event_id)


class EventClientsView(APIView):
    """GET: the event's client logins. POST: share the event with a client."""

    permission_classes = [IsStudioMember]

    def get(self, request, event_id):
        event = _studio_event(request, event_id)
        accesses = ClientAccess.objects.for_studio(request.studio_id).filter(event=event)
        return Response([_access_data(a) for a in accesses])

    def post(self, request, event_id):
        event = _studio_event(request, event_id)
        data = ShareRequest(data=request.data)
        data.is_valid(raise_exception=True)
        if event.status == Event.Status.ARCHIVED:
            return Response(
                {"detail": "This event is archived."}, status=status.HTTP_400_BAD_REQUEST
            )
        entitlements.require_can_work(request.studio_id)
        if settings.REQUIRE_VERIFIED_EMAIL_TO_SHARE:
            require_verified_email(request.user)
        ready = Photo.objects.for_studio(request.studio_id).filter(
            event=event, status=Photo.Status.READY
        )
        if not ready.exists():
            return Response(
                {"detail": "Upload photos before sharing the event."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        password = client_access.generate_password()
        with transaction.atomic():
            access = ClientAccess(
                studio_id=request.studio_id,
                event=event,
                client_name=data.validated_data["client_name"],
                email=data.validated_data["email"].lower(),
                phone=data.validated_data["phone"],
                username=client_access.generate_username(data.validated_data["client_name"]),
            )
            access.set_password(password)
            access.save()
            if event.status in (Event.Status.DRAFT, Event.Status.UPLOADING):
                event.status = Event.Status.SHARED
                event.save(update_fields=["status", "updated_at"])
            if access.email and settings.CLIENT_EMAIL_SHARING:  # otherwise the studio sends it
                emails.client_invitation_email(access, password)
            contact = ", ".join(c for c in (access.email, access.phone and f"+{access.phone}") if c)
            record(request, "client.shared", event, f"{access.client_name} ({contact})")
        # The password is shown once, here, and sent in the invitation email; only its hash is kept.
        return Response(
            {**_access_data(access), "password": password}, status=status.HTTP_201_CREATED
        )


class ClientAccessActionView(APIView):
    """POST /client-access/{id}/reset-password or /revoke."""

    permission_classes = [IsStudioMember]

    def post(self, request, pk, action):
        if action not in {"revoke", "reset-password"}:
            return Response(status=status.HTTP_404_NOT_FOUND)
        access = get_object_or_404(
            ClientAccess.objects.for_studio(request.studio_id).select_related("event", "studio"),
            pk=pk,
        )
        if action == "revoke":
            access.is_active = False
            access.save(update_fields=["is_active", "updated_at"])
            record(request, "client.access_turned_off", access.event, access.username)
            return Response(_access_data(access))
        entitlements.require_can_work(request.studio_id)
        if settings.REQUIRE_VERIFIED_EMAIL_TO_SHARE:
            require_verified_email(request.user)
        password = client_access.generate_password()
        access.set_password(password)
        access.is_active, access.failed_attempts, access.locked_until = True, 0, None
        access.save()
        if access.email and settings.CLIENT_EMAIL_SHARING:
            emails.client_invitation_email(access, password)
        record(request, "client.password_reset", access.event, access.username)
        return Response({**_access_data(access), "password": password})


class EventProgressView(APIView):
    permission_classes = [IsStudioMember]

    def get(self, request, event_id):
        event = _studio_event(request, event_id)
        submission = Submission.objects.for_studio(request.studio_id).filter(event=event).first()
        return Response(
            {
                "status": event.status,
                "selection_limit": event.selection_limit,
                "selected": Selection.objects.for_studio(request.studio_id)
                .filter(event=event)
                .count(),
                "submitted_at": submission.submitted_at if submission else None,
                "last_client_login": ClientAccess.objects.for_studio(request.studio_id)
                .filter(event=event)
                .exclude(last_login_at=None)
                .order_by("-last_login_at")
                .values_list("last_login_at", flat=True)
                .first(),
            }
        )


class EventReopenView(APIView):
    """Let the client change a submitted selection again."""

    permission_classes = [IsStudioMember]

    def post(self, request, event_id):
        event = _studio_event(request, event_id)
        if event.status != Event.Status.SUBMITTED:
            return Response(
                {"detail": "This selection is not submitted."}, status=status.HTTP_400_BAD_REQUEST
            )
        with transaction.atomic():
            Submission.objects.for_studio(request.studio_id).filter(event=event).delete()
            event.status = Event.Status.SHARED
            event.save(update_fields=["status", "updated_at"])
            record(request, "selection.reopened", event)
        return Response({"status": event.status})


# ---------------------------------------------------------------- client side


class ClientLoginAccountThrottle(FieldThrottle):
    scope = "client_login_account"
    field = "username"


class ClientLoginIpThrottle(IpThrottle):
    scope = "client_login_ip"


@method_decorator(csrf_protect, name="dispatch")
class ClientView(APIView):
    """Client endpoints: session-based, so CSRF is checked explicitly."""

    authentication_classes: list = []
    permission_classes = [client_access.IsClient]


class ClientLoginView(ClientView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientLoginAccountThrottle, ClientLoginIpThrottle]

    def post(self, request):
        username = str(request.data.get("username", "")).strip().lower()
        password = str(request.data.get("password", ""))
        # One answer for unknown usernames, wrong passwords and locked logins, so the
        # response never confirms that a username exists.
        refused = Response(
            {
                "detail": "Username or password is incorrect. "
                "After 5 wrong tries, wait 15 minutes before trying again."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
        with bypass_rls():  # the client's studio is not known until we find the login
            access = (
                ClientAccess.objects.select_related("event", "studio")
                .filter(username=username)
                .first()
            )
            if access is None or access.is_locked:
                return refused
            if not access.check_password(password):
                access.record_failure()
                return refused
            reason = client_access.unavailable_reason(access)
            if reason:
                return Response({"detail": reason}, status=status.HTTP_403_FORBIDDEN)
            access.failed_attempts, access.locked_until = 0, None
            access.last_login_at = timezone.now()
            access.save(
                update_fields=["failed_attempts", "locked_until", "last_login_at", "updated_at"]
            )
        client_access.start_session(request, access)
        return Response({"ok": True})


class ClientLogoutView(ClientView):
    permission_classes = [AllowAny]

    def post(self, request):
        client_access.end_session(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _cover_url(event) -> str | None:
    """The event's first photo, large, for the gallery's opening screen."""
    key = (
        Photo.objects.for_studio(event.studio_id)
        .filter(event=event, status=Photo.Status.READY)
        .order_by("sort_order", "relative_path")
        .values_list("preview_key", flat=True)
        .first()
    )
    return storage.signed_download_url(key) if key else None


class ClientMeView(ClientView):
    def get(self, request):
        event = request.client.event
        albums = Album.objects.for_studio(event.studio_id).filter(event=event)
        submission = Submission.objects.for_studio(event.studio_id).filter(event=event).first()
        return Response(
            {
                "client_name": request.client.client_name,
                "studio_name": request.client.studio.name,
                "event": {
                    "title": event.title,
                    "selection_limit": event.selection_limit,
                    "expires_at": event.expires_at,
                    "submitted_at": submission.submitted_at if submission else None,
                },
                "cover_url": _cover_url(event),
                "branding": client_branding(request.client.studio),
                "photo_count": Photo.objects.for_studio(event.studio_id)
                .filter(event=event, status=Photo.Status.READY)
                .count(),
                "selected": Selection.objects.for_studio(event.studio_id)
                .filter(event=event)
                .count(),
                "albums": [{"id": str(a.pk), "name": a.name} for a in albums],
            }
        )


class ClientPhotosView(ClientView):
    def get(self, request):
        event = request.client.event
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            size = min(PAGE_SIZE_MAX, max(1, int(request.query_params.get("page_size", 60))))
        except ValueError:
            return Response({"detail": "page and page_size must be numbers."}, status=400)
        photos = Photo.objects.for_studio(event.studio_id).filter(
            event=event, status=Photo.Status.READY
        )
        album = request.query_params.get("album")
        if album:
            try:
                uuid.UUID(album)
            except ValueError:
                return Response({"detail": "album must be an album ID."}, status=400)
            photos = photos.filter(album_id=album)
        notes = dict(
            Selection.objects.for_studio(event.studio_id)
            .filter(event=event)
            .values_list("photo_id", "note")
        )
        if request.query_params.get("selected") == "1":
            photos = photos.filter(pk__in=notes.keys())
        total = photos.count()
        rows = photos[(page - 1) * size : page * size]
        return Response(
            {
                "count": total,
                "next_page": page + 1 if page * size < total else None,
                "results": [
                    {
                        "id": str(p.pk),
                        "width": p.width,
                        "height": p.height,
                        "thumb_url": storage.signed_download_url(p.thumb_key),
                        "preview_url": storage.signed_download_url(p.preview_key),
                        "selected": p.pk in notes,
                        "note": notes.get(p.pk, ""),
                    }
                    for p in rows
                ],
            }
        )


class NoteRequest(serializers.Serializer):
    note = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class ClientSelectionView(ClientView):
    """PUT selects a photo (or updates its note); DELETE unselects it."""

    def _locked_event(self, request) -> Event:
        return (
            Event.objects.for_studio(request.client.studio_id)
            .select_for_update()
            .get(pk=request.client.event_id)
        )

    def put(self, request, photo_id):
        data = NoteRequest(data=request.data)
        data.is_valid(raise_exception=True)
        studio_id = request.client.studio_id
        photo = get_object_or_404(
            Photo.objects.for_studio(studio_id),
            pk=photo_id,
            event_id=request.client.event_id,
            status=Photo.Status.READY,
        )
        with transaction.atomic():
            event = self._locked_event(request)  # serialises selections so the limit holds
            if event.status == Event.Status.SUBMITTED:
                return Response(
                    {"detail": "Your selection is already submitted."},
                    status=status.HTTP_409_CONFLICT,
                )
            existing = (
                Selection.objects.for_studio(studio_id).filter(event=event, photo=photo).first()
            )
            if existing:
                existing.note = data.validated_data["note"]
                existing.save(update_fields=["note", "updated_at"])
            else:
                count = Selection.objects.for_studio(studio_id).filter(event=event).count()
                if event.selection_limit and count >= event.selection_limit:
                    return Response(
                        {
                            "detail": f"You have already selected {count} photos, the most allowed for this event."
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
                try:
                    with transaction.atomic():
                        Selection.objects.create(
                            studio_id=studio_id,
                            event=event,
                            photo=photo,
                            client_access=request.client,
                            note=data.validated_data["note"],
                        )
                except IntegrityError:
                    pass  # already selected from another device a moment ago
            selected = Selection.objects.for_studio(studio_id).filter(event=event).count()
        return Response(
            {"selected": True, "note": data.validated_data["note"], "selected_count": selected}
        )

    def delete(self, request, photo_id):
        studio_id = request.client.studio_id
        with transaction.atomic():
            event = self._locked_event(request)
            if event.status == Event.Status.SUBMITTED:
                return Response(
                    {"detail": "Your selection is already submitted."},
                    status=status.HTTP_409_CONFLICT,
                )
            Selection.objects.for_studio(studio_id).filter(event=event, photo_id=photo_id).delete()
            selected = Selection.objects.for_studio(studio_id).filter(event=event).count()
        return Response({"selected": False, "selected_count": selected})


class ClientSubmitView(ClientView):
    def post(self, request):
        studio_id = request.client.studio_id
        with transaction.atomic():
            event = (
                Event.objects.for_studio(studio_id)
                .select_for_update()
                .get(pk=request.client.event_id)
            )
            if event.status == Event.Status.SUBMITTED:
                return Response(
                    {"detail": "Your selection is already submitted."},
                    status=status.HTTP_409_CONFLICT,
                )
            count = Selection.objects.for_studio(studio_id).filter(event=event).count()
            if count == 0:
                return Response(
                    {"detail": "Select at least one photo first."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            submission = Submission.objects.create(
                studio_id=studio_id, event=event, client_access=request.client, photo_count=count
            )
            event.status = Event.Status.SUBMITTED
            event.save(update_fields=["status", "updated_at"])
            record(request, "selection.submitted", event, f"{count} photos", studio_id=studio_id)
            recipients = User.objects.filter(studio_id=studio_id, is_active=True).values_list(
                "email", flat=True
            )
            for email in recipients:
                emails.selection_submitted_email(email, event, count, request.client.client_name)
        return Response({"submitted_at": submission.submitted_at, "photo_count": count})


# ---------------------------------------------------------------- selection review, exports, archive


def _selection_rows(request, event) -> list:
    from .exports import Row

    selections = (
        Selection.objects.for_studio(request.studio_id)
        .filter(event=event)
        .select_related("photo", "photo__album")
        .order_by("photo__sort_order", "photo__relative_path")
    )
    return [
        (
            s,
            Row(
                photo_id=str(s.photo_id),
                relative_path=s.photo.relative_path,
                album=s.photo.album.name if s.photo.album else "",
                note=s.note,
                selected_at=s.created_at,
            ),
        )
        for s in selections
    ]


class EventSelectionView(APIView):
    """The client's selection, for the studio to review."""

    permission_classes = [IsStudioMember]

    def get(self, request, event_id):
        event = _studio_event(request, event_id)
        results = []
        for selection, row in _selection_rows(request, event):
            photo = selection.photo
            has_images = photo.status == Photo.Status.READY
            results.append(
                {
                    "photo_id": row.photo_id,
                    "relative_path": row.relative_path,
                    "filename": row.filename,
                    "album": row.album,
                    "note": row.note,
                    "selected_at": row.selected_at,
                    "thumb_url": storage.signed_download_url(photo.thumb_key)
                    if has_images
                    else None,
                    "preview_url": storage.signed_download_url(photo.preview_key)
                    if has_images
                    else None,
                }
            )
        names = [r["filename"].lower() for r in results]
        return Response(
            {
                "count": len(results),
                "duplicate_filenames": sorted({n for n in names if names.count(n) > 1}),
                "results": results,
            }
        )


class EventExportView(APIView):
    permission_classes = [IsStudioMember]

    def get(self, request, event_id):
        from django.http import HttpResponse

        from . import exports

        event = _studio_event(request, event_id)
        # Not "format": Django REST Framework reserves that query parameter.
        fmt = request.query_params.get("type", "csv")
        if fmt not in exports.FORMATS:
            return Response(
                {"detail": f"type must be one of {sorted(exports.FORMATS)}"}, status=400
            )
        rows = [row for _, row in _selection_rows(request, event)]
        if not rows:
            return Response(
                {"detail": "Nothing is selected yet."}, status=status.HTTP_400_BAD_REQUEST
            )
        client = (
            ClientAccess.objects.for_studio(request.studio_id)
            .filter(event=event)
            .values_list("client_name", flat=True)
            .first()
            or "the client"
        )
        file = exports.build(fmt, event.title, client, rows)
        record(request, "selection.exported", event, f"{fmt}, {len(rows)} photos")
        response = HttpResponse(file.content, content_type=file.content_type)
        response["Content-Disposition"] = f'attachment; filename="{file.filename}"'
        return response


class EventArchiveView(APIView):
    """POST /events/{id}/archive closes the gallery; /unarchive reopens it if images remain."""

    permission_classes = [IsStudioMember]

    def post(self, request, event_id, action):
        if action not in {"archive", "unarchive"}:
            return Response(status=status.HTTP_404_NOT_FOUND)
        event = _studio_event(request, event_id)
        if action == "archive":
            if event.status != Event.Status.ARCHIVED:
                event.status, event.archived_at = Event.Status.ARCHIVED, timezone.now()
                event.save(update_fields=["status", "archived_at", "updated_at"])
                record(request, "event.archived", event)
        else:
            if event.status != Event.Status.ARCHIVED:
                return Response({"detail": "This event is not archived."}, status=400)
            entitlements.check_event_limit(request.studio_id)
            if event.photos_deleted_at:
                return Response(
                    {
                        "detail": "The images of this event were already removed; it cannot be reopened."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            submitted = (
                Submission.objects.for_studio(request.studio_id).filter(event=event).exists()
            )
            shared = ClientAccess.objects.for_studio(request.studio_id).filter(event=event).exists()
            event.status = (
                Event.Status.SUBMITTED
                if submitted
                else Event.Status.SHARED
                if shared
                else Event.Status.UPLOADING
            )
            event.archived_at = None
            event.save(update_fields=["status", "archived_at", "updated_at"])
            record(request, "event.unarchived", event)
        return Response({"status": event.status, "archived_at": event.archived_at})
