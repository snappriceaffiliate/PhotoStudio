"""Shared base classes for tenant-owned data.

Every model that belongs to one studio inherits TenantModel. Views and services
read through `Model.objects.for_studio(studio_id)` so scoping is written once.
PostgreSQL row-level security policies are added in Sprint 1 as a second layer.
"""

import uuid

from django.db import models


class TenantQuerySet(models.QuerySet):
    def for_studio(self, studio_id):
        if studio_id is None:
            raise ValueError("A studio ID is required for tenant-owned data.")
        return self.filter(studio_id=studio_id)


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantModel(TimestampedModel):
    studio = models.ForeignKey("studios.Studio", on_delete=models.CASCADE, related_name="+")

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True
