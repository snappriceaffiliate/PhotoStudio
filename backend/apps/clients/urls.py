from django.urls import path

from . import views

urlpatterns = [
    # Studio side
    path("events/<uuid:event_id>/clients", views.EventClientsView.as_view(), name="event-clients"),
    path(
        "events/<uuid:event_id>/progress", views.EventProgressView.as_view(), name="event-progress"
    ),
    path("events/<uuid:event_id>/reopen", views.EventReopenView.as_view(), name="event-reopen"),
    path(
        "client-access/<uuid:pk>/<str:action>",
        views.ClientAccessActionView.as_view(),
        name="client-access-action",
    ),
    # Client gallery
    path("client/login", views.ClientLoginView.as_view(), name="client-login"),
    path("client/logout", views.ClientLogoutView.as_view(), name="client-logout"),
    path("client/me", views.ClientMeView.as_view(), name="client-me"),
    path("client/photos", views.ClientPhotosView.as_view(), name="client-photos"),
    path(
        "client/selections/<uuid:photo_id>",
        views.ClientSelectionView.as_view(),
        name="client-selection",
    ),
    path("client/submit", views.ClientSubmitView.as_view(), name="client-submit"),
]
