"""Studio branding: the logo and accent colour clients see in their gallery.

The browser turns the logo into a small WebP before upload, as it does for photos; the
server only checks the size and that the file really is WebP, then stores it.
"""

import re
import secrets

from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsStudioMember, IsStudioOwner
from apps.audit.models import record
from apps.billing import entitlements
from apps.core import storage
from apps.core.validators import single_line, whatsapp_number

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


def tone_of(data: bytes) -> str:
    """ "light" when the logo's visible pixels are mostly pale (white lettering on a
    transparent background), so it needs a dark backing to be seen; otherwise "dark"."""
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = opened.convert("RGBA")
    except Exception:  # not an image Pillow can read: show it on white, as before
        return "dark"
    image.thumbnail((200, 200))
    total = weight = 0.0
    pixels = image.tobytes()
    for i in range(0, len(pixels), 4):
        r, g, b, a = pixels[i], pixels[i + 1], pixels[i + 2], pixels[i + 3]
        if a < 40:
            continue
        total += (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 * a
        weight += a
    return "light" if weight and total / weight > 0.6 else "dark"


def logo_tone(studio: Studio) -> str | None:
    """The logo's tone; logos uploaded before tones existed are checked once, then saved."""
    if not studio.logo_key:
        return None
    if not studio.logo_tone:
        try:
            studio.logo_tone = tone_of(storage.read_object(studio.logo_key))
        except Exception:  # unreadable for now: show it on white, try again next time
            return "dark"
        Studio.objects.filter(pk=studio.pk).update(logo_tone=studio.logo_tone)
    return studio.logo_tone


def client_branding(studio: Studio) -> dict | None:
    """What the client gallery shows, or None for the standard PickSnap look."""
    if not (studio.logo_key or studio.accent_color):
        return None
    if not entitlements.branding_allowed(studio.pk):
        return None
    return {
        "logo_url": logo_url(studio),
        "logo_tone": logo_tone(studio),
        "accent_color": studio.accent_color or None,
    }


def _data(studio: Studio) -> dict:
    allowed = entitlements.branding_allowed(studio.pk)
    return {
        "studio_name": studio.name,
        "logo_url": logo_url(studio),
        "logo_tone": logo_tone(studio),
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
        studio.logo_tone = tone_of(data)
        studio.save(update_fields=["logo_key", "logo_tone", "updated_at"])
        if old_key:
            storage.delete_object(old_key)
        record(request, "studio.branding_logo", detail="uploaded")
        return Response(_data(studio), status=status.HTTP_201_CREATED)

    def delete(self, request):
        studio = Studio.objects.get(pk=request.studio_id)
        if studio.logo_key:
            storage.delete_object(studio.logo_key)
            studio.logo_key = studio.logo_tone = ""
            studio.save(update_fields=["logo_key", "logo_tone", "updated_at"])
            record(request, "studio.branding_logo", detail="removed")
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- Studio profile -------------------------------------------------------------------

PROFILE_FIELDS = ["name", "phone", "contact_email", "address", "city", "website", "instagram"]
INSTAGRAM_HANDLE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


class ProfileSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=200,
        validators=[single_line],
        error_messages={"blank": "Enter the studio's name."},
    )
    phone = serializers.CharField(max_length=30, allow_blank=True, required=False)
    address = serializers.CharField(
        max_length=300, allow_blank=True, required=False, validators=[single_line]
    )
    city = serializers.CharField(
        max_length=100, allow_blank=True, required=False, validators=[single_line]
    )
    website = serializers.CharField(max_length=200, allow_blank=True, required=False)
    instagram = serializers.CharField(max_length=60, allow_blank=True, required=False)

    class Meta:
        model = Studio
        fields = PROFILE_FIELDS

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter the studio's name.")
        return value

    def validate_phone(self, value):
        return whatsapp_number(value) if value.strip() else ""

    def validate_website(self, value):
        value = value.strip()
        if not value:
            return ""
        if not re.match(r"^https?://", value, re.I):
            value = f"https://{value}"
        serializers.URLField().run_validation(value)
        return value

    def validate_instagram(self, value):
        value = value.strip()
        # Accept @handle or a profile link and keep the bare handle.
        value = re.sub(r"^(https?://)?(www\.)?instagram\.com/", "", value, flags=re.I)
        value = value.strip("/").lstrip("@")
        if value and not INSTAGRAM_HANDLE.match(value):
            raise serializers.ValidationError(
                "Enter the Instagram handle, for example lensandlight."
            )
        return value


def studio_contact(studio: Studio) -> dict | None:
    """The contact details a client gallery shows, or None when the studio added none."""
    contact = {
        "phone": studio.phone or None,
        "email": studio.contact_email or None,
        "city": studio.city or None,
        "website": studio.website or None,
        "instagram": studio.instagram or None,
    }
    return contact if any(contact.values()) else None


class StudioProfileView(APIView):
    """GET the studio profile (owner and staff). PATCH it (owner only)."""

    permission_classes = [IsStudioMember]

    def get(self, request):
        return Response(ProfileSerializer(Studio.objects.get(pk=request.studio_id)).data)

    def patch(self, request):
        if not request.user.is_owner:
            return Response(
                {"detail": "Only the studio owner can change the studio profile."}, status=403
            )
        studio = Studio.objects.get(pk=request.studio_id)
        data = ProfileSerializer(studio, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        changed = [f for f, v in data.validated_data.items() if getattr(studio, f) != v]
        data.save()
        if changed:
            record(request, "studio.profile", detail=", ".join(changed))
        return Response(data.data)
