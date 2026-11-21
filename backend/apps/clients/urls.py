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
    path(
        "events/<uuid:event_id>/selection",
        views.EventSelectionView.as_view(),
        name="event-selection",
    ),
    path("events/<uuid:event_id>/export", views.EventExportView.as_view(), name="event-export"),
    path(
        "events/<uuid:event_id>/archive",
        views.EventArchiveView.as_view(),
        {"action": "archive"},
        name="event-archive",
    ),
    path(
        "events/<uuid:event_id>/unarchive",
        views.EventArchiveView.as_view(),
        {"action": "unarchive"},
        name="event-unarchive",
    ),
    path("reminders", views.RemindersView.as_view(), name="reminders"),
    path("reminders/<uuid:pk>/sent", views.ReminderSentView.as_view(), name="reminder-sent"),
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
