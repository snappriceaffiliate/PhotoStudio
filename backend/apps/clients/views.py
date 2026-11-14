from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsStudioMember
from apps.core import storage
from apps.core.tenancy import bypass_rls
from apps.events.models import Album, Event
from apps.notifications import emails
from apps.photos.models import Photo

from . import access as client_access
from .models import ClientAccess, Selection, Submission

PAGE_SIZE_MAX = 200

# ---------------------------------------------------------------- studio side


class ShareRequest(serializers.Serializer):
    client_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()


def _access_data(a: ClientAccess) -> dict:
    return {
        "id": str(a.pk),
        "client_name": a.client_name,
        "email": a.email,
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
                username=client_access.generate_username(data.validated_data["client_name"]),
            )
            access.set_password(password)
            access.save()
            if event.status in (Event.Status.DRAFT, Event.Status.UPLOADING):
                event.status = Event.Status.SHARED
                event.save(update_fields=["status", "updated_at"])
            emails.client_invitation_email(access, password)
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
            return Response(_access_data(access))
        password = client_access.generate_password()
        access.set_password(password)
        access.is_active, access.failed_attempts, access.locked_until = True, 0, None
        access.save()
        emails.client_invitation_email(access, password)
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
        return Response({"status": event.status})


# ---------------------------------------------------------------- client side


class ClientLoginThrottle(SimpleRateThrottle):
    scope = "login"

    def get_cache_key(self, request, view):
        username = str(request.data.get("username", "")).strip().lower()
        return self.cache_format % {
            "scope": "client-login",
            "ident": f"{username}|{self.get_ident(request)}",
        }


@method_decorator(csrf_protect, name="dispatch")
class ClientView(APIView):
    """Client endpoints: session-based, so CSRF is checked explicitly."""

    authentication_classes: list = []
    permission_classes = [client_access.IsClient]


class ClientLoginView(ClientView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientLoginThrottle]

    def post(self, request):
        username = str(request.data.get("username", "")).strip().lower()
        password = str(request.data.get("password", ""))
        refused = Response(
            {"detail": "Username or password is incorrect."}, status=status.HTTP_400_BAD_REQUEST
        )
        with bypass_rls():  # the client's studio is not known until we find the login
            access = (
                ClientAccess.objects.select_related("event", "studio")
                .filter(username=username)
                .first()
            )
            if access is None:
                return refused
            if access.is_locked:
                return Response(
                    {"detail": "Too many wrong passwords. Try again in 15 minutes."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
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
            recipients = User.objects.filter(studio_id=studio_id, is_active=True).values_list(
                "email", flat=True
            )
            for email in recipients:
                emails.selection_submitted_email(email, event, count, request.client.client_name)
        return Response({"submitted_at": submission.submitted_at, "photo_count": count})
