from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.core.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health", health, name="health"),
]

if settings.SPIKES_ENABLED:
    urlpatterns.append(path("api/v1/spike/", include("apps.spikes.urls")))
