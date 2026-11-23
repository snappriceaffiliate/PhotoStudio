from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django_otp.admin import OTPAdminSite
from rest_framework.routers import SimpleRouter

from apps.core.admin_login import OneStepOTPAdminAuthenticationForm
from apps.core.views import health, spa
from apps.events.views import AlbumViewSet, EventViewSet

# The Django admin (platform staff only) requires an authenticator-app code at login.
admin.site.__class__ = OTPAdminSite
admin.site.login_form = OneStepOTPAdminAuthenticationForm

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
    path("api/v1/", include("apps.billing.urls")),
    path("api/v1/", include("apps.studios.urls")),
]

if settings.SPIKES_ENABLED:
    urlpatterns.append(path("api/v1/spike/", include("apps.spikes.urls")))

# The copy tool lives at /copy/ (static files in the production image, served by WhiteNoise).
# A missing file under /copy/ is a 404, not the React app; /copy without the slash goes to /copy/.
urlpatterns.append(
    path("copy", RedirectView.as_view(url="/copy/", query_string=True), name="copy-tool")
)

# Every other path is a screen of the React app (production only; Vite serves it in development).
urlpatterns.append(re_path(r"^(?!api/|admin/|static/|copy/).*$", spa, name="spa"))
