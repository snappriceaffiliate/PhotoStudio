from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from apps.accounts.permissions import IsStudioMember
from apps.audit.models import record
from apps.billing import entitlements
from apps.core import storage
from apps.core.validators import single_line

from .models import Album, Event


class EventSerializer(serializers.ModelSerializer):
    photo_count = serializers.IntegerField(read_only=True, default=0)
    selected_count = serializers.IntegerField(read_only=True, default=0)
    cover_url = serializers.SerializerMethodField()

    def get_cover_url(self, obj) -> str | None:
        key = getattr(obj, "cover_key", None)
        return storage.signed_download_url(key) if key else None

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "event_date",
            "status",
            "selection_limit",
            "expires_at",
            "watermark_enabled",
            "watermark_text",
            "photo_count",
            "selected_count",
            "cover_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]
        # Empty means no limit; zero would make every choice fail while the client sees no limit.
        extra_kwargs = {"selection_limit": {"min_value": 1}}

    def validate_title(self, value):
        return single_line(value)

    def validate_watermark_text(self, value):
        return single_line(value)

    def validate(self, attrs):
        enabled = attrs.get("watermark_enabled", getattr(self.instance, "watermark_enabled", False))
        text = attrs.get("watermark_text", getattr(self.instance, "watermark_text", ""))
        if enabled and not text.strip():
            raise serializers.ValidationError(
                {"watermark_text": ["Enter the watermark text, for example your studio name."]}
            )
        return attrs


class EventViewSet(viewsets.ModelViewSet):
    """Events of the logged-in user's studio."""

    serializer_class = EventSerializer
    permission_classes = [IsStudioMember]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        from apps.photos.models import Photo

        first_photo = Photo.objects.filter(event=OuterRef("pk"), status="ready").order_by(
            "sort_order", "relative_path"
        )
        return Event.objects.for_studio(self.request.studio_id).annotate(
            photo_count=Count("photos", filter=Q(photos__status="ready"), distinct=True),
            selected_count=Count("selections", distinct=True),
            cover_key=Subquery(first_photo.values("thumb_key")[:1]),
        )

    def perform_create(self, serializer):
        entitlements.check_event_limit(self.request.studio_id)
        serializer.save(studio_id=self.request.studio_id, created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Deletes the event with its photos, client logins and selection. Owner only.

        The rows go now; the stored images are deleted by a background job.
        """
        from apps.photos import tasks

        if not request.user.is_owner:
            return Response(
                {"detail": "Only the studio owner can delete an event."},
                status=status.HTTP_403_FORBIDDEN,
            )
        event = self.get_object()
        studio_id, event_id = str(event.studio_id), str(event.pk)
        with transaction.atomic():
            record(request, "event.deleted", None, f"{event.title} ({event.photo_count} photos)")
            event.delete()
            transaction.on_commit(
                lambda: tasks.delete_event_files.defer(studio_id=studio_id, event_id=event_id)
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class AlbumSerializer(serializers.ModelSerializer):
    photo_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Album
        fields = ["id", "event", "name", "sort_order", "photo_count", "created_at"]
        read_only_fields = ["id", "event", "created_at"]

    def validate_name(self, value):
        return single_line(value)


class AlbumViewSet(viewsets.ModelViewSet):
    """Albums of one event: /events/{event_id}/albums and /albums/{id}."""

    serializer_class = AlbumSerializer
    permission_classes = [IsStudioMember]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        albums = Album.objects.for_studio(self.request.studio_id).annotate(
            photo_count=Count("photos", filter=Q(photos__status="ready"))
        )
        if "event_pk" in self.kwargs:
            albums = albums.filter(event_id=self.kwargs["event_pk"])
        return albums

    def create(self, request, *args, **kwargs):
        event = (
            Event.objects.for_studio(request.studio_id).filter(pk=kwargs.get("event_pk")).first()
        )
        if event is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        data = AlbumSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        name = data.validated_data["name"].strip()
        if (
            Album.objects.for_studio(request.studio_id)
            .filter(event=event, name__iexact=name)
            .exists()
        ):
            return Response(
                {"name": ["This event already has an album with that name."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        next_order = event.albums.count()
        album = Album.objects.create(
            studio_id=request.studio_id,
            event=event,
            name=name,
            sort_order=data.validated_data.get("sort_order", next_order),
        )
        return Response(AlbumSerializer(album).data, status=status.HTTP_201_CREATED)
