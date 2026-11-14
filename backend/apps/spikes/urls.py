from django.urls import path

from .views import ConfirmView, UploadUrlView

urlpatterns = [
    path("upload-url", UploadUrlView.as_view(), name="spike-upload-url"),
    path("confirm", ConfirmView.as_view(), name="spike-confirm"),
]
