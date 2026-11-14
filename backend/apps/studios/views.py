"""Studio branding: the logo and accent colour clients see in their gallery.

The browser turns the logo into a small WebP before upload, as it does for photos; the
server only checks the size and that the file really is WebP, then stores it.
"""

import re
import secrets

from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsStudioOwner
from apps.audit.models import record
from apps.billing import entitlements
from apps.core import storage

from .models import Studio

LOGO_MAX_BYTES = 60 * 1024
HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
MIN_CONTRAST = 4.5  # against white, so links and button labels stay readable (WCAG AA)


def _luminance(hex_colour: str) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_with_white(hex_colour: str) -> float:
    return 1.05 / (_luminance(hex_colour) + 0.05)


def logo_url(studio: Studio) -> str | None:
    return storage.signed_download_url(studio.logo_key) if studio.logo_key else None


def client_branding(studio: Studio) -> dict | None:
    """What the client gallery shows, or None for the standard PickSnap look."""
    if not (studio.logo_key or studio.accent_color):
        return None
    if not entitlements.branding_allowed(studio.pk):
        return None
    return {"logo_url": logo_url(studio), "accent_color": studio.accent_color or None}


def _data(studio: Studio) -> dict:
    allowed = entitlements.branding_allowed(studio.pk)
    return {
        "studio_name": studio.name,
        "logo_url": logo_url(studio),
        "accent_color": studio.accent_color or None,
        "allowed": allowed,
    }


class BrandingView(APIView):
    """GET the studio's branding. PATCH {accent_color} ("" or null resets it)."""

    permission_classes = [IsStudioOwner]

    def get(self, request):
        return Response(_data(Studio.objects.get(pk=request.studio_id)))

    def patch(self, request):
        entitlements.require_branding(request.studio_id)
        studio = Studio.objects.get(pk=request.studio_id)
        colour = request.data.get("accent_color") or ""
        if colour:
            if not isinstance(colour, str) or not HEX_COLOUR.match(colour):
                return Response({"accent_color": ["Use a colour code like #8A1C3B."]}, status=400)
            if contrast_with_white(colour) < MIN_CONTRAST:
                return Response(
                    {
                        "accent_color": [
                            "This colour is too light for text on white. Pick a darker shade."
                        ]
                    },
                    status=400,
                )
            colour = colour.upper()
        studio.accent_color = colour
        studio.save(update_fields=["accent_color", "updated_at"])
        record(request, "studio.branding_colour", detail=colour or "reset")
        return Response(_data(studio))


class BrandingLogoView(APIView):
    """POST a WebP logo (multipart field "logo"). DELETE removes it."""

    permission_classes = [IsStudioOwner]
    parser_classes = [MultiPartParser]

    def post(self, request):
        entitlements.require_branding(request.studio_id)
        upload = request.FILES.get("logo")
        if upload is None:
            return Response({"logo": ["Choose a logo file."]}, status=400)
        if upload.size > LOGO_MAX_BYTES:
            return Response({"logo": ["The logo must be under 60 KB after resizing."]}, status=400)
        data = upload.read()
        if not storage.is_webp(data[:12]):
            return Response({"logo": ["The logo must be a WebP image."]}, status=400)
        studio = Studio.objects.get(pk=request.studio_id)
        old_key = studio.logo_key
        studio.logo_key = f"studios/{studio.pk}/logo/{secrets.token_hex(8)}.webp"
        storage.put_object(studio.logo_key, data, "image/webp")
        studio.save(update_fields=["logo_key", "updated_at"])
        if old_key:
            storage.delete_object(old_key)
        record(request, "studio.branding_logo", detail="uploaded")
        return Response(_data(studio), status=status.HTTP_201_CREATED)

    def delete(self, request):
        studio = Studio.objects.get(pk=request.studio_id)
        if studio.logo_key:
            storage.delete_object(studio.logo_key)
            studio.logo_key = ""
            studio.save(update_fields=["logo_key", "updated_at"])
            record(request, "studio.branding_logo", detail="removed")
        return Response(status=status.HTTP_204_NO_CONTENT)
