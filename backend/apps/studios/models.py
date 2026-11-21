from django.db import models

from apps.core.models import TimestampedModel


class Studio(TimestampedModel):
    """One subscribing business: the tenant that owns events, photos and staff."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)
    # Branding shown to clients in galleries (plans with custom_branding only).
    logo_key = models.CharField(max_length=200, blank=True)
    accent_color = models.CharField(max_length=7, blank=True, help_text="Hex colour, e.g. #8A1C3B.")
    # Studio profile: how clients reach the studio. Shown in client galleries when filled in.
    phone = models.CharField(
        max_length=16, blank=True, help_text="WhatsApp number, country code and digits only."
    )
    contact_email = models.EmailField(blank=True)
    address = models.CharField(max_length=300, blank=True)
    city = models.CharField(max_length=100, blank=True)
    website = models.URLField(max_length=200, blank=True)
    instagram = models.CharField(max_length=30, blank=True, help_text="Handle without the @.")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
