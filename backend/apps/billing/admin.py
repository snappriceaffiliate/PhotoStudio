from django.contrib import admin

from .models import Plan, Subscription, WebhookEvent


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "code",
        "price_paise",
        "max_active_events",
        "max_photos_per_event",
        "max_staff",
        "custom_branding",
        "razorpay_plan_id",
        "is_public",
    ]
    list_editable = ["is_public"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = [
        "studio",
        "status",
        "plan",
        "trial_ends_at",
        "current_period_end",
        "cancel_at_period_end",
        "razorpay_status",
    ]
    list_filter = ["status", "plan"]
    search_fields = ["studio__name", "razorpay_subscription_id"]
    raw_id_fields = ["studio"]


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "event", "razorpay_subscription_id", "processed"]
    list_filter = ["event", "processed"]
    search_fields = ["event_id", "razorpay_subscription_id"]
    readonly_fields = ["event_id", "event", "razorpay_subscription_id", "payload", "processed"]
