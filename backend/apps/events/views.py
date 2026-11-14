from rest_framework import serializers, viewsets

from apps.accounts.permissions import IsStudioMember

from .models import Event


class EventSerializer(serializers.ModelSerializer):
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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]


class EventViewSet(viewsets.ModelViewSet):
    """Events of the logged-in user's studio. Albums, upload and sharing come in Sprint 2."""

    serializer_class = EventSerializer
    permission_classes = [IsStudioMember]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return Event.objects.for_studio(self.request.studio_id)

    def perform_create(self, serializer):
        serializer.save(studio_id=self.request.studio_id, created_by=self.request.user)
