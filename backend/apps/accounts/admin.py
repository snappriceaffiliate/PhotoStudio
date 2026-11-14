from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = [
        "email",
        "full_name",
        "studio",
        "role",
        "is_active",
        "email_verified_at",
        "is_staff",
    ]
    list_filter = ["role", "is_active", "is_staff"]
    search_fields = ["email", "full_name", "studio__name"]
    readonly_fields = ["date_joined", "last_login"]
    fieldsets = [
        (None, {"fields": ["email", "password", "full_name"]}),
        ("Studio", {"fields": ["studio", "role", "email_verified_at"]}),
        ("Platform", {"fields": ["is_active", "is_staff", "is_superuser"]}),
        ("Dates", {"fields": ["date_joined", "last_login"]}),
    ]
    add_fieldsets = [
        (None, {"classes": ["wide"], "fields": ["email", "full_name", "password1", "password2"]})
    ]
    filter_horizontal = []
