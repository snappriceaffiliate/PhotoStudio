from django.urls import path

from . import views

urlpatterns = [
    path("studio/branding", views.BrandingView.as_view(), name="studio-branding"),
    path("studio/branding/logo", views.BrandingLogoView.as_view(), name="studio-branding-logo"),
]
