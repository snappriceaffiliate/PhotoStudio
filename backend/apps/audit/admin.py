from django.contrib import admin

from .models import AuditEntry


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    list_display = ["created_at", "studio", "actor_label", "action", "event", "detail"]
    list_filter = ["action"]
    search_fields = ["actor_label", "detail", "studio__name", "event__title"]
    raw_id_fields = ["studio", "actor_user", "event"]

    def has_change_permission(self, request, obj=None):
        return False  # the log is append-only

    def has_add_permission(self, request):
        return False
