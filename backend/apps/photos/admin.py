from django.contrib import admin

from .models import Photo, UploadSession


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ["relative_path", "event", "studio", "status", "preview_bytes", "thumb_bytes"]
    list_filter = ["status", "source"]
    search_fields = ["relative_path", "event__title", "studio__name"]
    raw_id_fields = ["studio", "event", "album", "upload"]


@admin.register(UploadSession)
class UploadSessionAdmin(admin.ModelAdmin):
    list_display = ["id", "event", "studio", "status", "created_at", "completed_at"]
    list_filter = ["status"]
    raw_id_fields = ["studio", "event", "created_by"]
