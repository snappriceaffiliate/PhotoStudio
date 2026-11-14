"""Upload API: register files, get signed upload URLs, confirm, complete; and the photo list.

Flow per upload run (see frontend/src/upload/uploader.ts):
1. POST /events/{id}/uploads                 -> a new upload session
2. POST /uploads/{id}/files     (<= 2000)    -> one Photo row per file; READY ones are skipped
3. POST /uploads/{id}/urls      (<= 50)      -> signed PUT URLs for preview and thumbnail
4. browser PUTs both images straight to storage
5. POST /uploads/{id}/confirm   (<= 50)      -> server checks both objects, marks READY or FAILED
6. POST /uploads/{id}/complete               -> closes the session and returns totals
"""

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsStudioMember
from apps.core import storage
from apps.events.models import Album, Event

from .models import Photo, UploadSession

FILES_PER_CALL = 2000
PHOTOS_PER_BATCH = 50
PAGE_SIZE_MAX = 200


class FileEntry(serializers.Serializer):
    relative_path = serializers.CharField(max_length=1024)
    album_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_relative_path(self, value):
        value = value.replace("\\", "/").strip("/")
        if not value or ".." in value.split("/"):
            raise serializers.ValidationError("Invalid file path.")
        return value


class FilesRequest(serializers.Serializer):
    files = FileEntry(many=True, allow_empty=False, max_length=FILES_PER_CALL)


class PhotoIdsRequest(serializers.Serializer):
    photo_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=PHOTOS_PER_BATCH
    )


class ConfirmEntry(serializers.Serializer):
    id = serializers.UUIDField()
    width = serializers.IntegerField(min_value=1, max_value=20000)
    height = serializers.IntegerField(min_value=1, max_value=20000)
    source = serializers.ChoiceField(choices=Photo.Source.values)


class ConfirmRequest(serializers.Serializer):
    photos = ConfirmEntry(many=True, allow_empty=False, max_length=PHOTOS_PER_BATCH)


def _event(request, event_id) -> Event:
    return get_object_or_404(Event.objects.for_studio(request.studio_id), pk=event_id)


def _session(request, upload_id) -> UploadSession:
    return get_object_or_404(
        UploadSession.objects.for_studio(request.studio_id).select_related("event"), pk=upload_id
    )


def _status_entry(photo: Photo) -> dict:
    return {"id": str(photo.pk), "relative_path": photo.relative_path, "status": photo.status}


class StudioView(APIView):
    permission_classes = [IsStudioMember]


class UploadCreateView(StudioView):
    def post(self, request, event_id):
        event = _event(request, event_id)
        if event.status == Event.Status.ARCHIVED:
            return Response(
                {"detail": "This event is archived."}, status=status.HTTP_400_BAD_REQUEST
            )
        with transaction.atomic():
            session = UploadSession.objects.create(
                studio_id=request.studio_id, event=event, created_by=request.user
            )
            if event.status == Event.Status.DRAFT:
                event.status = Event.Status.UPLOADING
                event.save(update_fields=["status", "updated_at"])
        return Response(
            {"id": str(session.pk), "event": str(event.pk)}, status=status.HTTP_201_CREATED
        )


class UploadFilesView(StudioView):
    """Registers files. Re-registering a path resumes it; READY photos are never uploaded twice."""

    def post(self, request, upload_id):
        session = _session(request, upload_id)
        data = FilesRequest(data=request.data)
        data.is_valid(raise_exception=True)
        entries = data.validated_data["files"]

        album_ids = {e["album_id"] for e in entries if e.get("album_id")}
        albums = set(
            Album.objects.for_studio(request.studio_id)
            .filter(event=session.event, pk__in=album_ids)
            .values_list("pk", flat=True)
        )
        if album_ids - albums:
            return Response(
                {"detail": "An album does not belong to this event."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        photos = Photo.objects.for_studio(request.studio_id).filter(event=session.event)
        paths = [e["relative_path"] for e in entries]
        existing = {p.relative_path: p for p in photos.filter(relative_path__in=paths)}
        new_entries = [e for e in entries if e["relative_path"] not in existing]
        if photos.count() + len(new_entries) > settings.MAX_PHOTOS_PER_EVENT:
            return Response(
                {"detail": f"An event can hold at most {settings.MAX_PHOTOS_PER_EVENT} photos."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            next_order = (photos.aggregate(m=Max("sort_order"))["m"] or 0) + 1
            created = Photo.objects.bulk_create(
                [
                    Photo(
                        studio_id=request.studio_id,
                        event=session.event,
                        upload=session,
                        album_id=e.get("album_id"),
                        relative_path=e["relative_path"],
                        original_filename=e["relative_path"].rsplit("/", 1)[-1],
                        sort_order=next_order + i,
                    )
                    for i, e in enumerate(new_entries)
                ]
            )
            retry = [p for p in existing.values() if p.status != Photo.Status.READY]
            for photo in retry:
                photo.upload, photo.status, photo.failure_reason = session, Photo.Status.PENDING, ""
            Photo.objects.bulk_update(retry, ["upload", "status", "failure_reason"])

        by_path = {p.relative_path: p for p in [*created, *existing.values()]}
        return Response({"files": [_status_entry(by_path[p]) for p in paths]})


class UploadUrlsView(StudioView):
    def post(self, request, upload_id):
        session = _session(request, upload_id)
        data = PhotoIdsRequest(data=request.data)
        data.is_valid(raise_exception=True)
        photos = list(
            Photo.objects.for_studio(request.studio_id).filter(
                upload=session, status=Photo.Status.PENDING, pk__in=data.validated_data["photo_ids"]
            )
        )
        for photo in photos:
            prefix = photo.storage_prefix()
            photo.preview_key, photo.thumb_key = f"{prefix}/preview.webp", f"{prefix}/thumb.webp"
        Photo.objects.bulk_update(photos, ["preview_key", "thumb_key"])
        return Response(
            {
                "max_bytes": settings.MAX_IMAGE_BYTES,
                "urls": [
                    {
                        "id": str(p.pk),
                        "preview_url": storage.signed_upload_url(p.preview_key, "image/webp"),
                        "thumb_url": storage.signed_upload_url(p.thumb_key, "image/webp"),
                    }
                    for p in photos
                ],
            }
        )


class UploadConfirmView(StudioView):
    """Checks each stored object. Anything missing or over 100 KB is refused and deleted."""

    def post(self, request, upload_id):
        session = _session(request, upload_id)
        data = ConfirmRequest(data=request.data)
        data.is_valid(raise_exception=True)
        entries = {e["id"]: e for e in data.validated_data["photos"]}
        photos = Photo.objects.for_studio(request.studio_id).filter(
            upload=session, pk__in=entries, status=Photo.Status.PENDING
        )
        results = []
        for photo in photos:
            entry = entries[photo.pk]
            sizes = [
                storage.object_size(k) if k else None for k in (photo.preview_key, photo.thumb_key)
            ]
            if None in sizes:
                photo.status, photo.failure_reason = Photo.Status.FAILED, "Upload did not arrive."
            elif max(sizes) > settings.MAX_IMAGE_BYTES:
                for key in (photo.preview_key, photo.thumb_key):
                    storage.delete_object(key)
                photo.status, photo.failure_reason = Photo.Status.FAILED, "Image is over 100 KB."
            else:
                photo.status, photo.failure_reason = Photo.Status.READY, ""
                photo.preview_bytes, photo.thumb_bytes = sizes
                photo.width, photo.height, photo.source = (
                    entry["width"],
                    entry["height"],
                    entry["source"],
                )
            photo.save()
            results.append({**_status_entry(photo), "failure_reason": photo.failure_reason})
        return Response({"results": results})


class UploadCompleteView(StudioView):
    def post(self, request, upload_id):
        session = _session(request, upload_id)
        if session.status == UploadSession.Status.OPEN:
            session.status, session.completed_at = UploadSession.Status.COMPLETED, timezone.now()
            session.save(update_fields=["status", "completed_at", "updated_at"])
        photos = Photo.objects.for_studio(request.studio_id).filter(upload=session)
        totals = {s: photos.filter(status=s).count() for s in Photo.Status.values}
        return Response({"id": str(session.pk), "status": session.status, "totals": totals})


class PhotoListView(StudioView):
    """Ready photos of an event, paged, with 15-minute signed image URLs."""

    def get(self, request, event_id):
        event = _event(request, event_id)
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            size = min(PAGE_SIZE_MAX, max(1, int(request.query_params.get("page_size", 100))))
        except ValueError:
            return Response({"detail": "page and page_size must be numbers."}, status=400)
        photos = Photo.objects.for_studio(request.studio_id).filter(
            event=event, status=Photo.Status.READY
        )
        album = request.query_params.get("album")
        if album == "none":
            photos = photos.filter(album__isnull=True)
        elif album:
            photos = photos.filter(album_id=album)
        total = photos.count()
        rows = photos[(page - 1) * size : page * size]
        return Response(
            {
                "count": total,
                "page": page,
                "next_page": page + 1 if page * size < total else None,
                "results": [
                    {
                        "id": str(p.pk),
                        "relative_path": p.relative_path,
                        "original_filename": p.original_filename,
                        "album": str(p.album_id) if p.album_id else None,
                        "width": p.width,
                        "height": p.height,
                        "thumb_url": storage.signed_download_url(p.thumb_key),
                        "preview_url": storage.signed_download_url(p.preview_key),
                    }
                    for p in rows
                ],
            }
        )
