from django.db import models

from apps.core.models import TimestampedModel


class Studio(TimestampedModel):
    """One subscribing business: the tenant that owns events, photos and staff."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
