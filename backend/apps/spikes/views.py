"""Sprint 0 storage spike: signed upload, server-side size check, signed delivery.

These endpoints have no authentication and exist only when SPIKES_ENABLED is set.
The real upload API (Sprint 2) reuses apps.core.storage with tenant checks.
"""

import re
import uuid

from django.conf import settings
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import storage

ALLOWED_TYPES = {"image/webp", "image/jpeg"}
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class UploadRequest(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.ChoiceField(choices=sorted(ALLOWED_TYPES))
    size = serializers.IntegerField(min_value=1)

    def validate_size(self, value):
        if value > settings.MAX_IMAGE_BYTES:
            raise serializers.ValidationError(
                f"Image is {value} bytes; the limit is {settings.MAX_IMAGE_BYTES} bytes."
            )
        return value


class ConfirmRequest(serializers.Serializer):
    key = serializers.RegexField(r"^spike/[0-9a-f-]{36}/[A-Za-z0-9._-]+$")


class SpikeView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]


class UploadUrlView(SpikeView):
    def post(self, request):
        data = UploadRequest(data=request.data)
        data.is_valid(raise_exception=True)
        name = SAFE_NAME.sub("_", data.validated_data["filename"])[:120] or "image"
        key = f"spike/{uuid.uuid4()}/{name}"
        url = storage.signed_upload_url(key, data.validated_data["content_type"])
        return Response({"key": key, "upload_url": url, "expires_in": settings.SIGNED_URL_SECONDS})


class ConfirmView(SpikeView):
    def post(self, request):
        data = ConfirmRequest(data=request.data)
        data.is_valid(raise_exception=True)
        key = data.validated_data["key"]
        size = storage.object_size(key)
        if size is None:
            return Response({"detail": "Object not found."}, status=status.HTTP_404_NOT_FOUND)
        if size > settings.MAX_IMAGE_BYTES:
            storage.delete_object(key)
            return Response(
                {"detail": f"Stored object is {size} bytes, over the limit; it was deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"key": key, "size": size, "download_url": storage.signed_download_url(key)}
        )
