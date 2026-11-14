from django.urls import path

from . import views

urlpatterns = [
    path("billing", views.BillingView.as_view(), name="billing"),
    path("billing/subscribe", views.SubscribeView.as_view(), name="billing-subscribe"),
    path("billing/verify", views.VerifyView.as_view(), name="billing-verify"),
    path("billing/cancel", views.CancelView.as_view(), name="billing-cancel"),
    path("billing/webhook", views.webhook, name="billing-webhook"),
]
