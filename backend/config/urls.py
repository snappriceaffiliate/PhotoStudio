from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from rest_framework.routers import SimpleRouter

from apps.core.views import health, spa
from apps.events.views import AlbumViewSet, EventViewSet

router = SimpleRouter(trailing_slash=False)
router.register("events", EventViewSet, basename="event")

album_list = AlbumViewSet.as_view({"get": "list", "post": "create"})
album_detail = AlbumViewSet.as_view(
    {"get": "retrieve", "patch": "partial_update", "delete": "destroy"}
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health", health, name="health"),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include(router.urls)),
    path("api/v1/events/<uuid:event_pk>/albums", album_list, name="album-list"),
    path("api/v1/albums/<uuid:pk>", album_detail, name="album-detail"),
    path("api/v1/", include("apps.photos.urls")),
    path("api/v1/", include("apps.clients.urls")),
]

if settings.SPIKES_ENABLED:
    urlpatterns.append(path("api/v1/spike/", include("apps.spikes.urls")))

# Every other path is a screen of the React app (production only; Vite serves it in development).
urlpatterns.append(re_path(r"^(?!api/|admin/|static/).*$", spa, name="spa"))
