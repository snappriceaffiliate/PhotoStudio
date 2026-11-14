from django.contrib import admin

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "studio", "status", "event_date", "created_at"]
    list_filter = ["status"]
    search_fields = ["title", "studio__name"]
    raw_id_fields = ["studio", "created_by"]
