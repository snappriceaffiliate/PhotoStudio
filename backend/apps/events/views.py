from django.db.models import Count, Q
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from apps.accounts.permissions import IsStudioMember

from .models import Album, Event


class EventSerializer(serializers.ModelSerializer):
    photo_count = serializers.IntegerField(read_only=True, default=0)

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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]

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
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return Event.objects.for_studio(self.request.studio_id).annotate(
            photo_count=Count("photos", filter=Q(photos__status="ready"))
        )

    def perform_create(self, serializer):
        serializer.save(studio_id=self.request.studio_id, created_by=self.request.user)


class AlbumSerializer(serializers.ModelSerializer):
    photo_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Album
        fields = ["id", "event", "name", "sort_order", "photo_count", "created_at"]
        read_only_fields = ["id", "event", "created_at"]


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
