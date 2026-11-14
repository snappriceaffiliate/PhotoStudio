from django.urls import path

from . import views

urlpatterns = [
    path("events/<uuid:event_id>/uploads", views.UploadCreateView.as_view(), name="upload-create"),
    path("events/<uuid:event_id>/photos", views.PhotoListView.as_view(), name="photo-list"),
    path("uploads/<uuid:upload_id>/files", views.UploadFilesView.as_view(), name="upload-files"),
    path("uploads/<uuid:upload_id>/urls", views.UploadUrlsView.as_view(), name="upload-urls"),
    path(
        "uploads/<uuid:upload_id>/confirm", views.UploadConfirmView.as_view(), name="upload-confirm"
    ),
    path(
        "uploads/<uuid:upload_id>/complete",
        views.UploadCompleteView.as_view(),
        name="upload-complete",
    ),
]
