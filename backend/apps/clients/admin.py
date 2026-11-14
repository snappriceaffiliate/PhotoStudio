from django.contrib import admin

from .models import ClientAccess, Selection, Submission


@admin.register(ClientAccess)
class ClientAccessAdmin(admin.ModelAdmin):
    list_display = [
        "username",
        "client_name",
        "email",
        "phone",
        "event",
        "studio",
        "is_active",
        "last_login_at",
    ]
    list_filter = ["is_active"]
    search_fields = ["username", "client_name", "email", "event__title"]
    raw_id_fields = ["studio", "event"]
    exclude = ["password_hash"]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["event", "studio", "photo_count", "submitted_at"]
    raw_id_fields = ["studio", "event", "client_access"]


@admin.register(Selection)
class SelectionAdmin(admin.ModelAdmin):
    list_display = ["photo", "event", "studio", "created_at"]
    raw_id_fields = ["studio", "event", "photo", "client_access"]
